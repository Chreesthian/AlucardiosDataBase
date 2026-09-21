"""Sincronización incremental del árbol MEGA contra la BD local.

Objetivo: escaneos periódicos que detectan archivos/carpetas **añadidos y
borrados** sin "rehacer" la base de datos.

Cómo funciona (en el snapshot vigente, en sitio):
  1. Parsa el volcado nuevo y calcula el diff contra las rutas ya guardadas.
  2. SUSTRACCIÓN: borra únicamente los nodos que ya no existen (con sus
     títulos, por cascada) → nada más se toca.
  3. ADICIÓN: inserta únicamente los nodos nuevos (con su jerarquía).
  4. Cambios de tamaño en archivos → se actualiza el tamaño.
  5. Recalcula (barato, O(n) en memoria) agregados de carpetas, roles y los
     resúmenes de títulos derivados. Los títulos que PERSISTEN conservan su
     enriquecimiento IGDB (`igdb_slug/igdb_cover/igdb_json`).
  6. Registra el escaneo en `sync_logs` (añadidos/borrados/cambiados).

Si no hay snapshot previo, hace la ingesta inicial completa (bootstrap).

Uso:
    uv run python -m app.sync --dump ../mega_cuenta_contenido_MEGAcmd.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import build_engine, create_schema
from .ingest import bucket_letter, classify_version, ingest, is_bucket
from .models import DownloadLink, Node, Snapshot, SyncLog, Title
from .normalize import normalize, slugify
from .novedades import registrar_novedades
from .parser import Node as PNode
from .parser import ParsedDump, parse_text

log = logging.getLogger("alucard.sync")


def _collect(parsed: ParsedDump) -> dict[str, PNode]:
    """Rutas deseadas tras el nuevo escaneo (path → PNode del parser)."""
    nuevo: dict[str, PNode] = {}

    def walk(n: PNode, path: str) -> None:
        nuevo[path] = n
        for c in n.children:
            walk(c, f"{path}/{c.name}")

    for sec in parsed.sectors:
        for root in sec.roots:
            walk(root, root.name)
    return nuevo


# ── Rotación de share (credenciales semanales) ───────────────────────────────
# La cuenta MEGA rota cada semana y con ella el share montado
# (`INSHARE dueño:BCKP1` → `INSHARE otro:BCKP2`) aunque la biblioteca sea la
# MISMA. Tratarlo como borrado+alta masivo perdería los ids de nodo, el
# enriquecimiento IGDB y llenaría "Novedades" de falsos juegos nuevos; por eso se
# detecta el cambio de prefijo y se REMAPEAN las rutas guardadas.
UMBRAL_ALIAS = 0.5  # solape mínimo de rutas (sin prefijo) para ser la misma biblioteca
MIN_RUTAS_ALIAS = 50  # tamaño mínimo del sector para poder comparar


def _prefijos(rutas) -> dict[str, set[str]]:
    """{primer segmento: {rutas sin ese prefijo}} (el sector es el primer segmento)."""
    out: dict[str, set[str]] = defaultdict(set)
    for p in rutas:
        prefijo, _, resto = p.partition("/")
        out[prefijo].add(resto)
    return out


def detectar_rotacion_share(exist, nuevo) -> list[tuple[str, str]]:
    """[(prefijo_viejo, prefijo_nuevo)] de shares que aportan la MISMA biblioteca."""
    viejos, nuevos = _prefijos(exist), _prefijos(nuevo)
    fuera = [
        p
        for p in viejos
        if p not in nuevos and p.startswith("INSHARE") and len(viejos[p]) >= MIN_RUTAS_ALIAS
    ]
    dentro = {
        p
        for p in nuevos
        if p not in viejos and p.startswith("INSHARE") and len(nuevos[p]) >= MIN_RUTAS_ALIAS
    }
    pares: list[tuple[str, str]] = []
    for viejo in sorted(fuera):
        candidatos = sorted(
            (
                (len(viejos[viejo] & nuevos[n]) / min(len(viejos[viejo]), len(nuevos[n])), n)
                for n in dentro
            ),
            reverse=True,
        )
        if not candidatos or candidatos[0][0] < UMBRAL_ALIAS:
            continue
        solape, elegido = candidatos[0]
        dentro.discard(elegido)
        log.warning(
            "rotación de share detectada: %s → %s (solape %.0f%%; se remapan las rutas)",
            viejo,
            elegido,
            solape * 100,
        )
        pares.append((viejo, elegido))
    return pares


def _remapear_prefijo(session: Session, sid: int, viejo: str, nuevo: str) -> None:
    """Reescribe rutas de `viejo` → `nuevo` conservando ids de nodo y títulos.

    Los `node_id` y el árbol (`parent_id`) no cambian, así que los títulos y su
    enriquecimiento IGDB sobreviven. Los enlaces de descarga cacheados apuntan al
    share antiguo: se reinician (`pendiente`) para volver a indexarlos contra el
    share nuevo con `scripts/enlazar_descargas.sh`.
    """
    largo = len(viejo)
    # Restos de una rotación previa a medio aplicar (evita chocar con el índice único).
    session.execute(
        delete(DownloadLink).where(
            DownloadLink.snapshot_id == sid, DownloadLink.path.startswith(nuevo + "/", autoescape=True)
        )
    )
    for modelo in (Node, DownloadLink):
        session.execute(
            update(modelo)
            .where(modelo.snapshot_id == sid, modelo.path.startswith(viejo + "/", autoescape=True))
            .values(path=nuevo + func.substr(modelo.path, largo + 1))
        )
    session.execute(
        update(Node).where(Node.snapshot_id == sid, Node.path == viejo).values(path=nuevo)
    )
    session.execute(
        update(DownloadLink)
        .where(DownloadLink.snapshot_id == sid, DownloadLink.path == nuevo)
        .values(estado="pendiente", link=None, error=None, generado_en=None)
    )
    session.execute(
        update(DownloadLink)
        .where(DownloadLink.snapshot_id == sid, DownloadLink.path.startswith(nuevo + "/", autoescape=True))
        .values(estado="pendiente", link=None, error=None, generado_en=None)
    )


def refresh(
    engine,
    parsed: ParsedDump,
    *,
    kind: str = "dump",
    source_path: str | None = None,
    allow_empty: bool = False,
    min_fraccion: float = 0.5,
) -> dict:
    """Actualiza la BD por diferencias. Devuelve resumen del escaneo.

    Blindaje 1: si la BD tiene contenido y el nuevo volcado NO trae archivos
    (fichero vacío/truncado/borrado por error), aborta en vez de vaciar la
    biblioteca. `allow_empty=True` fuerza el vaciado consciente (CLI --allow-vacio).
    Blindaje 2 (fallo rápido y ruidoso del pipeline): si el volcado pierde más de
    `1 - min_fraccion` de los archivos actuales se aborta, porque eso es lo que
    produce un volcado a medio escribir (el refresco se escribe EN SITIO sobre el
    inodo que monta Docker). `min_fraccion=0` desactiva la comprobación.
    """
    stats = {
        "kind": kind,
        "source_path": source_path,
        "bootstrap": False,
        "added_files": 0,
        "removed_files": 0,
        "changed_files": 0,
        "added_folders": 0,
        "removed_folders": 0,
        "novedades": 0,
        "rotados": [],
        "total_files": parsed.file_count,
        "total_folders": parsed.folder_count,
    }

    with Session(engine) as session:
        snap = session.execute(
            select(Snapshot).order_by(Snapshot.id.desc()).limit(1)
        ).scalar_one_or_none()

        if snap is None:
            # Primera vez: ingesta completa (bootstrap), no hay nada que destruir.
            ingest(engine, parsed, source_kind=kind, source_path=source_path)
            stats["bootstrap"] = True
            stats["added_files"] = parsed.file_count
            stats["added_folders"] = parsed.folder_count
            return stats

        sid = snap.id
        filas = list(session.execute(select(Node).where(Node.snapshot_id == sid)).scalars())
        exist = {r.path: r for r in filas}
        nuevo = _collect(parsed)

        # Rotación de credenciales: el share montado cambia, la biblioteca no.
        # Se remapan las rutas ANTES del diff para que el catálogo, los títulos y
        # el IGDB sobrevivan (y "Novedades" solo registre lo realmente nuevo).
        rotados = detectar_rotacion_share(exist, nuevo)
        if rotados:
            for viejo_pref, nuevo_pref in rotados:
                _remapear_prefijo(session, sid, viejo_pref, nuevo_pref)
            # Las rutas se han reescrito con SQL masivo: hay que descartar la
            # caché de identidad o el diff seguiría viendo los caminos antiguos.
            session.expire_all()
            session.flush()
            filas = list(session.execute(select(Node).where(Node.snapshot_id == sid)).scalars())
            exist = {r.path: r for r in filas}
            stats["rotados"] = [[v, n] for v, n in rotados]

        # Blindaje: un volcado vacío/truncado NUNCA debe vaciar la biblioteca.
        actuales_archivos = sum(1 for r in filas if r.kind == "file")
        if actuales_archivos and parsed.file_count == 0 and not allow_empty:
            raise RuntimeError(
                "Volcado sin archivos (file_count=0) pero la BD tiene "
                f"{actuales_archivos} archivos → se ABORTA para no borrar nada. "
                "Si el vaciado es intencionado, vuelve a ejecutar con --allow-vacio."
            )
        # Blindaje 2: caída MASIVA de archivos = volcado truncado/a medio escribir.
        if (
            actuales_archivos
            and min_fraccion > 0
            and parsed.file_count < actuales_archivos * min_fraccion
            and not allow_empty
        ):
            raise RuntimeError(
                f"Volcado sospechoso: {parsed.file_count} archivos frente a "
                f"{actuales_archivos} en la BD (< {min_fraccion:.0%}) → se ABORTA "
                "para no borrar media biblioteca (¿escritura en curso o volcado a "
                "medias?). Reintenta cuando el refresco acabe; si la bajada es "
                "intencionada, usa --min-fraccion 0 o --allow-vacio."
            )

        # 1) SUSTRACCIÓN: rutas que ya no existen en el escaneo.
        removidos = set(exist) - set(nuevo)
        for p in removidos:
            session.delete(exist[p])
            if exist[p].kind == "file":
                stats["removed_files"] += 1
            else:
                stats["removed_folders"] += 1

        # 2) ADICIÓN: rutas nuevas (padres antes que hijos).
        añadidos = sorted(
            (set(nuevo) - set(exist)),
            key=lambda x: (len(x.split("/")), x),
        )
        max_order = max((r.node_order for r in filas), default=0)
        order = max_order + 1
        by_path: dict[str, Node] = {p: r for p, r in exist.items() if p not in removidos}
        insertados: list[tuple[str, Node]] = []
        for p in añadidos:
            n = nuevo[p]
            row = Node(
                snapshot_id=sid,
                path=p,
                name=n.name,
                depth=n.depth,
                kind="folder" if n.is_folder else "file",
                role="",
                ext=n.ext,
                size=0 if n.is_folder else n.size,
                node_order=order,
            )
            session.add(row)
            order += 1
            insertados.append((p, row))
            by_path[p] = row
            if n.is_folder:
                stats["added_folders"] += 1
            else:
                stats["added_files"] += 1
        session.flush()

        for p, row in insertados:
            parent = p.rsplit("/", 1)[0] if "/" in p else None
            row.parent_id = by_path[parent].id if parent else None

        # 3) Cambios: mismo archivo con otro tamaño.
        for p in set(exist) & set(nuevo):
            e, n = exist[p], nuevo[p]
            if not n.is_folder and e.size != n.size:
                e.size = n.size
                stats["changed_files"] += 1

        # 4) Estado derivado (agregados/roles/títulos) sobre el árbol final.
        _recalcular(session, sid)
        # 5) Novedades (sección "Novedades"): juegos nuevos y contenido nuevo.
        #    El flush previo garantiza que los títulos recién creados ya tienen
        #    id/slug para asociar los eventos.
        session.flush()
        stats["novedades"] = registrar_novedades(session, sid, añadidos, nuevo)

        snap.file_count = parsed.file_count
        snap.folder_count = parsed.folder_count
        snap.total_size = parsed.total_size
        snap.content_sha256 = parsed.sha256
        # Cabecera del volcado vigente: el volcado se regenera (nueva fecha,
        # cuenta y herramienta) y el snapshot debe reflejarlo, no quedar con la
        # cabecera de la primera ingesta.
        snap.account = parsed.account or snap.account
        snap.tool = parsed.tool or snap.tool
        snap.generated_at = parsed.generated_at or snap.generated_at
        if source_path:
            snap.source_path = source_path

        session.add(
            SyncLog(
                snapshot_id=sid,
                kind=kind,
                source_path=source_path,
                added_files=stats["added_files"],
                removed_files=stats["removed_files"],
                changed_files=stats["changed_files"],
                added_folders=stats["added_folders"],
                removed_folders=stats["removed_folders"],
                total_files=parsed.file_count,
                total_folders=parsed.folder_count,
            )
        )
        session.commit()
    return stats


def _rol_hijo(parent_role: str | None, nombre: str, kind: str) -> str:
    if parent_role is None:
        return "root"
    if parent_role == "root":
        return "bucket" if is_bucket(nombre) else ""
    if parent_role == "bucket":
        return "title" if kind == "folder" else ""
    if parent_role == "title":
        return "version" if kind == "folder" else ""
    return ""


def _recalcular(session: Session, sid: int) -> None:
    """Reasigna roles y agregados y refresca títulos derivados (en sitio).

    Solo sobreescribe lo derivado: los títulos que persisten conservan su
    `igdb_slug/igdb_cover/igdb_json`; los nuevos se crean; los eliminados se
    borran (ya cascadearon al quitar su nodo).
    """
    nodos = list(session.execute(select(Node).where(Node.snapshot_id == sid)).scalars())
    hijos: dict[int, list[Node]] = defaultdict(list)
    for r in nodos:
        if r.parent_id is not None:
            hijos[r.parent_id].append(r)
    titulos = {
        t.node_id: t
        for t in session.execute(select(Title).where(Title.snapshot_id == sid)).scalars()
    }
    usados = {t.slug for t in titulos.values()}
    titulos_vivos: set[int] = set()

    def _nuevo_slug(nombre: str) -> str:
        base = slugify(nombre)
        slug = base
        n = 2
        while slug in usados:
            slug = f"{base}-{n}"
            n += 1
        usados.add(slug)
        return slug

    def walk(row: Node, parent_role: str | None, letra_bucket: str):
        role = _rol_hijo(parent_role, row.name, row.kind)
        row.role = role if row.kind == "folder" else ""
        if row.kind != "folder":
            return row.size, 1, 0, Counter({row.ext: 1} if row.ext else {})

        size = files = folders = 0
        ext_sum = Counter()
        versiones: Counter = Counter()
        for child in hijos.get(row.id, []):
            if child.kind == "file":
                size += child.size
                files += 1
                if child.ext:
                    ext_sum[child.ext] += 1
                child.total_size, child.total_files, child.total_folders = child.size, 1, 0
                continue
            letra_hijo = (
                bucket_letter(row.name)
                if role == "bucket"
                else (
                    bucket_letter(child.name) if (role == "root" and is_bucket(child.name)) else ""
                )
            )
            s, f, d, ex = walk(child, role, letra_hijo)
            size += s
            files += f
            folders += d + 1
            ext_sum.update(ex)
            if role == "title":
                versiones[classify_version(child.name)] += 1

        row.total_size, row.total_files, row.total_folders = size, files, folders

        if role == "title":
            titulos_vivos.add(row.id)
            ext_json = json.dumps(dict(ext_sum), ensure_ascii=False)
            t = titulos.get(row.id)
            if t is None:
                session.add(
                    Title(
                        snapshot_id=sid,
                        node_id=row.id,
                        slug=_nuevo_slug(row.name),
                        name=row.name,
                        name_norm=normalize(row.name),
                        letter=letra_bucket,
                        size_bytes=size,
                        file_count=files,
                        folder_count=folders,
                        base_count=versiones["base"],
                        update_count=versiones["update"],
                        dlc_count=versiones["dlc"],
                        other_count=versiones["other"],
                        ext_json=ext_json,
                    )
                )
            else:
                # Conserva igdb_*; refresca solo lo derivado del árbol.
                t.size_bytes, t.file_count, t.folder_count = size, files, folders
                t.base_count, t.update_count = versiones["base"], versiones["update"]
                t.dlc_count, t.other_count = versiones["dlc"], versiones["other"]
                t.ext_json = ext_json
        return size, files, folders, ext_sum

    for r in nodos:
        if r.parent_id is None:
            walk(r, None, "")

    # Títulos huérfanos (su nodo dejó de ser título o fue borrado).
    for node_id, t in titulos.items():
        if node_id not in titulos_vivos:
            session.delete(t)


def refresh_file(
    engine,
    path: Path,
    *,
    kind: str = "dump",
    allow_empty: bool = False,
    min_fraccion: float = 0.5,
) -> dict:
    """Lee el volcado UNA sola vez (hash y parse del MISMO texto) y sincroniza."""
    texto = path.read_text(encoding="utf-8")
    parsed = parse_text(texto, sha256=hashlib.sha256(texto.encode("utf-8")).hexdigest())
    return refresh(
        engine,
        parsed,
        kind=kind,
        source_path=str(path),
        allow_empty=allow_empty,
        min_fraccion=min_fraccion,
    )


def refresh_text(
    engine,
    texto: str,
    *,
    kind: str = "dump",
    allow_empty: bool = False,
    min_fraccion: float = 0.5,
) -> dict:
    return refresh(
        engine,
        parse_text(texto),
        kind=kind,
        source_path=None,
        allow_empty=allow_empty,
        min_fraccion=min_fraccion,
    )


def _make_engine(db_arg: str | None = None):
    if db_arg:
        p = Path(db_arg).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{p}"
    else:
        url = settings.resolved_database_url
    create_schema(url)
    return build_engine(url)


def _huella(path: Path) -> str:
    """SHA-256 del volcado (detección de cambios para el modo --watch)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


# ── Frescura del volcado: el pipeline NO debe pararse en silencio ────────────
# El vigía puede aplicar diffs, pero no puede regenerar la fuente; si el refresco
# automático (scripts/autovolcado.sh vía cron) se rompe, el vigía seguiría
# diciendo "sin cambios" indefinidamente. Por eso comprueba la edad del volcado
# en CADA ciclo y, si está caducado, lo grita y sale con `EXIT_VOLCADO_OBSOLETO`
# (Docker reinicia el worker → estado visible en `docker compose ps`).
EXIT_VOLCADO_OBSOLETO = 3
_RE_FECHA_VOLCADO = re.compile(r"^\s*Fecha de volcado\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
# Los bloques SECTOR van al principio del volcado, pero el INSHARE real aparece
# más abajo (línea ~42): se lee una ventana mayor para localizar la biblioteca.
_RE_SECTOR_INSHARE = re.compile(r"^\s*SECTOR:\s*(INSHARE\s+\S+)\s*$", re.MULTILINE)
_LINEAS_CABECERA = 40
_LINEAS_FUENTE = 200


def _cabecera(path: Path, lineas: int = _LINEAS_CABECERA) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return "".join(islice(fh, lineas))
    except OSError:
        return ""


def fecha_generada(path: Path) -> str | None:
    """`Fecha de volcado` de la cabecera (la reescribe el propio volcador)."""
    m = _RE_FECHA_VOLCADO.search(_cabecera(path))
    return m.group(1) if m else None


def fuente_volcado(path: Path) -> str | None:
    """Share(s) que aportan la biblioteca: identidad ESTABLE del catálogo.

    Las etiquetas `INSHARE <dueño>:<carpeta>` las fija el share montado, no la
    cuenta activa: la rotación semanal de credenciales no cambia de dónde salen
    los datos (solo cambia `account` en la cabecera del volcado).
    """
    etiquetas = [m.strip() for m in _RE_SECTOR_INSHARE.findall(_cabecera(path, _LINEAS_FUENTE))]
    return ", ".join(etiquetas) if etiquetas else None


def _momento(valor: str | None) -> datetime | None:
    """ISO → datetime UTC (una fecha sin zona se interpreta como UTC)."""
    if not valor:
        return None
    try:
        d = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def frescura(path: Path, max_edad_horas: int = 0, *, ahora: datetime | None = None) -> dict:
    """Edad del volcado (horas) y si supera `max_edad_horas` (0 = sin límite).

    Usa la fecha de la cabecera (autorrefrescada al volcar) y cae al `mtime`
    cuando el volcado no la trae (volcados antiguos o hechos a mano).
    """
    ahora = (ahora or datetime.now(UTC)).astimezone(UTC)
    fecha = fecha_generada(path)
    momento, origen = _momento(fecha), "cabecera"
    if momento is None:
        try:
            momento, origen = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC), "mtime"
        except OSError:
            momento, origen = None, "desconocido"
    edad = round((ahora - momento).total_seconds() / 3600, 1) if momento else None
    return {
        "generated_at": fecha,
        "fuente": fuente_volcado(path),
        "edad_horas": edad,
        "origen": origen,
        "max_edad_horas": max_edad_horas,
        "obsoleto": bool(max_edad_horas and edad is not None and edad > max_edad_horas),
    }


def comprobar_frescura(path: Path, max_edad_horas: int, *, tolerar: bool = False) -> int:
    """Avisa (ruidoso) y devuelve el código de salida si el volcado está caducado.

    `tolerar=True` registra el error pero deja continuar (escaneo manual).
    """
    info = frescura(path, max_edad_horas)
    edad = "?" if info["edad_horas"] is None else f"{info['edad_horas']:.1f}"
    if not info["obsoleto"]:
        log.info(
            "volcado %s: %s h (origen=%s, límite=%s)",
            path,
            edad,
            info["origen"],
            f"{max_edad_horas} h" if max_edad_horas else "sin límite",
        )
        return 0
    mensaje = (
        f"VOLCADO OBSOLETO: {path} tiene {edad} h (límite {max_edad_horas} h; "
        f"cabecera={info['generated_at'] or 'sin fecha'}). El pipeline de "
        "actualización está PARADO: la BD, los escaneos y las novedades NO se "
        "están actualizando. Refréscalo con `make volcado` "
        "(scripts/refrescar_volcado.py) o automatízalo con `make volcado-cron`."
    )
    if tolerar:
        log.error("%s (se continúa: --seguir-si-obsoleto)", mensaje)
        return 0
    log.critical("%s Se aborta el vigía (rc=%s) para que el fallo sea visible.", mensaje, EXIT_VOLCADO_OBSOLETO)
    return EXIT_VOLCADO_OBSOLETO


def _una_pasada(
    engine, path: Path, exportar: bool, allow_vacio: bool = False, min_fraccion: float = 0.5
) -> dict:
    info = frescura(path)
    edad = "?" if info["edad_horas"] is None else f"{info['edad_horas']:.1f}"
    print(f"Volcado: {info['generated_at'] or 'sin cabecera'} (hace {edad} h, origen={info['origen']})")
    stats = refresh_file(
        engine, path, kind="dump", allow_empty=allow_vacio, min_fraccion=min_fraccion
    )
    print(
        f"[{stats['kind']}] bootstrap={stats['bootstrap']} | "
        f"+{stats['added_files']} archivos +{stats['added_folders']} carpetas | "
        f"-{stats['removed_files']} archivos -{stats['removed_folders']} carpetas | "
        f"~{stats['changed_files']} cambiados | novedades={stats.get('novedades', 0)}"
    )
    print(f"Estado final: {stats['total_files']} archivos, " f"{stats['total_folders']} carpetas.")
    if stats.get("rotados"):
        pares = ", ".join(f"{v} → {n}" for v, n in stats["rotados"])
        print(f"Rotación de share remapada (misma biblioteca): {pares}")
    if exportar:
        from .exportdb import export

        destino = Path(settings.resolved_db_path).parent / "biblioteca.json"
        meta = export(engine, out=destino)
        print(f"Exportado a {destino} (juegos={meta['total_juegos']})")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Escaneo incremental: actualiza la BD por diferencias "
        "(añadidos/borrados) sin reconstruir."
    )
    ap.add_argument(
        "--dump",
        default=str(settings.resolved_dump),
        help="Ruta al volcado .txt (o volcado MEGAcmd actual)",
    )
    ap.add_argument("--db", default=None, help="Ruta SQLite")
    ap.add_argument(
        "--export", action="store_true", help="Regenera data/biblioteca.json tras sincronizar"
    )
    ap.add_argument(
        "--watch",
        action="store_true",
        help="Modo daemon: vigila el volcado y sincroniza SOLO cuando cambia",
    )
    ap.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Segundos entre comprobaciones en --watch (def. 300)",
    )
    ap.add_argument(
        "--allow-vacio",
        action="store_true",
        help="Permite aplicar un volcado con 0 archivos (vaciado consciente)",
    )
    ap.add_argument(
        "--max-edad",
        type=int,
        default=settings.sync_max_edad_horas,
        help="Horas máximas de antigüedad del volcado antes de considerarlo "
        f"OBSOLETO en --watch (def. {settings.sync_max_edad_horas}; 0 = sin límite)",
    )
    ap.add_argument(
        "--seguir-si-obsoleto",
        action="store_true",
        help="No salir con error cuando el volcado está obsoleto (solo avisar)",
    )
    ap.add_argument(
        "--min-fraccion",
        type=float,
        default=settings.sync_min_fraccion,
        help="Fracción mínima de archivos que debe conservar el volcado para "
        f"aplicarse (def. {settings.sync_min_fraccion}; 0 = sin límite)",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    path = Path(args.dump).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"Volcado no encontrado: {path}")

    engine = _make_engine(args.db)

    if not args.watch:
        # Escaneo manual: se aplica aunque el volcado esté viejo (lo pidió el
        # operador), pero el aviso queda registrado como ERROR.
        comprobar_frescura(path, args.max_edad, tolerar=True)
        _una_pasada(engine, path, args.export, args.allow_vacio, args.min_fraccion)
        return

    # ── Modo daemon autónomo: espera a que el volcado cambie en disco. ──
    print(
        f"[sync-watch] vigilando {path} cada {args.interval}s "
        f"(frescura máx. {args.max_edad} h; primer escaneo inmediato). "
        "Detén con señal/Ctrl+C."
    )
    ultima_huella: str | None = None
    while True:
        try:
            if not path.exists():
                # Puede ser un arranque limpio sin volcado: reintenta con aviso.
                log.error("volcado ausente: %s; reintento en %ss", path, args.interval)
            else:
                # Sin fuente fresca no tiene sentido mirar el hash: se falla
                # rápido y ruidoso para que el pipeline parado se vea.
                rc = comprobar_frescura(
                    path, args.max_edad, tolerar=args.seguir_si_obsoleto
                )
                if rc:
                    raise SystemExit(rc)
                huella = _huella(path)
                if huella != ultima_huella:
                    ultima_huella = huella
                    _una_pasada(engine, path, args.export, args.allow_vacio, args.min_fraccion)
                else:
                    log.info(
                        "volcado sin cambios (huella=%s…); próxima comprobación en %ss",
                        huella[:12],
                        args.interval,
                    )
        except KeyboardInterrupt:
            print("[sync-watch] detenido.")
            return
        except SystemExit:
            raise
        except Exception:
            log.exception("error en pasada de sync; reintento en %ss", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
