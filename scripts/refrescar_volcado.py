#!/usr/bin/env python3
"""Refresca el volcado canónico de la cuenta MEGA (`mega-ls -R -l` → árbol ASCII).

Requiere una sesión MEGAcmd activa en `~/.megaCmd` (`mega-whoami`). El script:

  1. Descubre la cuenta activa (`mega-whoami`) y las raíces montadas
     (`mega-mount`: Cloud Drive, Inbox, Papelera e *in-shares*).
  2. Vuelca cada raíz con `mega-ls -R -l` al directorio de trabajo.
  3. Construye el árbol ASCII que consume `app.parser` conservando las MISMAS
     etiquetas de sector (`CLOUD_DRIVE`, `INBOX`, `RUBBISH_BIN`,
     `INSHARE <cuenta>:<carpeta>`) que el volcado vigente, de modo que el diff
     de `app.sync` sea incremental (los títulos que persisten conservan su
     enriquecimiento IGDB).
  4. Muestra el diff frente al volcado actual (rutas añadidas/eliminadas,
     ficheros con tamaño distinto) y aborta si el resultado vaciaría la
     biblioteca.
  5. Escribe el volcado EN SITIO (mismo inodo) para que los contenedores que lo
     montan por bind-mount (`backend`, `backend-sync`) vean el contenido nuevo
     sin reiniciar; `app.sync` lo detecta por hash en ≤300 s.

Uso:
    cd backend && uv run python ../scripts/refrescar_volcado.py --dry-run
    cd backend && uv run python ../scripts/refrescar_volcado.py

Variables de entorno:
    MEGA_BIN   directorio de los binarios MEGAcmd (def. /home/christian/opt/megacmd/usr/bin)
    MEGA_OUT   volcado de salida (def. <raíz del repo>/mega_cuenta_contenido_MEGAcmd.txt)
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from build_megacmd_dump import build_lines, human, parse_listing  # noqa: E402

from app.parser import parse_file, parse_text  # noqa: E402

MEGA_BIN_DEFAULT = "/home/christian/opt/megacmd/usr/bin"
DUMP_DEFAULT = ROOT / "mega_cuenta_contenido_MEGAcmd.txt"
TOOL = "MEGAcmd 2.6.0 (mega-ls -R -l)"

# Raíces fijas de la cuenta: (título de sector, ruta MEGA, etiqueta [ROOT]).
RAICES_FIJAS = [
    ("CLOUD_DRIVE", "/", "/"),
    ("INBOX", "//in", "//in"),
    ("RUBBISH_BIN", "//bin", "//bin"),
]

_RE_CUENTA = re.compile(r"Account e-mail:\s*(\S+)")
_RE_INSHARE = re.compile(r"^INSHARE on (\S+)", re.MULTILINE)


def _binario(nombre: str, mega_bin: Path) -> str:
    """Ruta absoluta al binario MEGAcmd (`--mega-bin` → PATH)."""
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    candidato = mega_bin / nombre
    if candidato.is_file():
        return str(candidato)
    raise SystemExit(f"MEGAcmd no disponible: no encuentro {nombre!r} (revisa --mega-bin)")


def _mega(args: list[str], mega_bin: Path, timeout: int) -> str:
    """Ejecuta un comando MEGAcmd y devuelve su stdout (nunca credenciales).

    Los wrappers `mega-*` invocan `mega-exec`, así que el directorio de los
    binarios se antepone al PATH del proceso hijo (igual que
    `scripts/enlazar_descargas.sh`).
    """
    binario = _binario(args[0], mega_bin)
    entorno = os.environ.copy()
    rutas = [str(mega_bin), str(Path(binario).parent)]
    entorno["PATH"] = os.pathsep.join([*rutas, entorno.get("PATH", "")])
    proc = subprocess.run(  # noqa: S603 — binario resuelto con shutil.which/--mega-bin
        [binario, *args[1:]],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=entorno,
    )
    salida = proc.stdout or ""
    if proc.returncode != 0 and not salida.strip():
        error = (proc.stderr or "").strip().splitlines()
        detalle = error[0] if error else "sin salida"
        raise SystemExit(f"{args[0]} falló (rc={proc.returncode}): {detalle}")
    return salida


def cuenta_activa(mega_bin: Path) -> str:
    m = _RE_CUENTA.search(_mega(["mega-whoami"], mega_bin, 60))
    if not m:
        raise SystemExit("Sin sesión MEGAcmd activa: ejecuta `mega-login` antes de refrescar.")
    return m.group(1)


def raices_inshare(mega_bin: Path) -> list[str]:
    """Rutas `//from/<cuenta>:<carpeta>` de los *in-shares* montados."""
    return [m.group(1) for m in _RE_INSHARE.finditer(_mega(["mega-mount"], mega_bin, 60))]


def etiqueta_sector(ruta: str) -> str:
    """Etiqueta estable de sector de una raíz MEGA (la del volcado canónico)."""
    for titulo, raiz, _ in RAICES_FIJAS:
        if ruta == raiz:
            return titulo
    resto = ruta[len("//from/") :] if ruta.startswith("//from/") else ruta
    return f"INSHARE {resto}"


def sectores(mega_bin: Path, compartidos: list[str] | None = None) -> list[tuple[str, str, str]]:
    """[(título de sector, ruta MEGA, etiqueta [ROOT])] de la cuenta activa."""
    out = list(RAICES_FIJAS)
    for ruta in raices_inshare(mega_bin) if compartidos is None else compartidos:
        out.append((etiqueta_sector(ruta), ruta, ruta))
    return out


def volcar_listados(
    sectores_: list[tuple[str, str, str]],
    mega_bin: Path,
    destino: Path,
    timeout: int,
    *,
    reusar: bool = False,
) -> dict[str, Path]:
    """`mega-ls -R -l` por sector → {título de sector: fichero de listado}."""
    destino.mkdir(parents=True, exist_ok=True)
    listados: dict[str, Path] = {}
    for titulo, ruta, _ in sectores_:
        archivo = destino / f"{titulo.replace(' ', '_')}.txt"
        if reusar and archivo.is_file() and archivo.stat().st_size:
            print(f"   · reutilizo {archivo.name}")
        else:
            print(f"   · mega-ls -R -l {ruta}")
            salida = _mega(["mega-ls", "-R", "-l", ruta], mega_bin, timeout)
            archivo.write_text(salida, encoding="utf-8")
        listados[titulo] = archivo
    return listados


def construir_volcado(
    sectores_: list[tuple[str, str, str]], listados: dict[str, Path], cuenta: str
) -> tuple[str, dict[str, int]]:
    """Árbol ASCII canónico (mismo formato que `build_megacmd_dump.main`)."""
    body: list[str] = []
    total = {"files": 0, "folders": 0, "bytes": 0}
    for titulo, _, raiz in sectores_:
        nodes = parse_listing(listados[titulo])
        lineas, counts = build_lines(nodes, raiz)
        body += [
            "",
            "=" * 72,
            f"SECTOR: {titulo}",
            "=" * 72,
            f"Archivos  : {counts['files']}",
            f"Carpetas  : {counts['folders']}",
            f"Tamano    : {counts['bytes']} bytes ({human(counts['bytes'])})",
            "",
            *lineas,
        ]
        total["files"] += counts["files"]
        total["folders"] += counts["folders"]
        total["bytes"] += counts["bytes"]

    ahora = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    hdr = [
        "VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)",
        "=" * 72,
        f"Cuenta            : {cuenta}",
        f"Fecha de volcado  : {ahora}",
        f"Herramienta       : {TOOL}",
        f"Archivos          : {total['files']}",
        f"Carpetas          : {total['folders']}",
        f"Tamano total      : {total['bytes']} bytes ({human(total['bytes'])})",
        "Formato           : arbol, [ROOT]/[FOLDER]/[FILE]",
        "",
    ]
    return "\n".join(hdr + body) + "\n", total


def _rutas(parsed) -> dict[str, tuple[str, int]]:
    """{ruta: (kind, size)} con la MISMA lógica de rutas que `app.sync._collect`."""
    from app.sync import _collect  # import diferido: solo se necesita para el diff

    return {p: (n.kind, n.size) for p, n in _collect(parsed).items()}


_RE_ARCHIVOS = re.compile(r"^\s*Archivos\s*:\s*(\d+)\s*$")


def sectores_con_archivos(texto: str) -> set[str]:
    """Etiquetas de `SECTOR:` que aportan al menos un archivo (la biblioteca real).

    Las etiquetas las fija `app.parser` a partir del SHARE montado
    (`INSHARE <dueño>:<carpeta>`), no de la cuenta activa: por eso sirven como
    identidad estable cuando las credenciales rotan semana a semana.
    """
    actual, out = None, set()
    for linea in texto.splitlines():
        if linea.startswith("SECTOR:"):
            actual = linea.split("SECTOR:", 1)[1].strip()
        elif actual:
            m = _RE_ARCHIVOS.match(linea)
            if m and int(m.group(1)) > 0:
                out.add(actual)
    return out


def _rotaciones(viejo_texto: str, nuevo_texto: str) -> list[tuple[str, str]]:
    """Pares (sector viejo, sector nuevo) que son la MISMA biblioteca.

    Las credenciales semanales traen otro share montado con los mismos datos
    (`INSHARE dueño:BCKP1` → `INSHARE otro:BCKP2`). Se reutiliza el mismo criterio
    que `app.sync` (solape de rutas sin el prefijo) para no bloquear el refresco
    legítimo; sin el entorno del backend no se puede comprobar y se es conservador.
    """
    try:
        from app.sync import _collect, detectar_rotacion_share
    except ImportError:
        return []
    viejo = {p: (n.kind, n.size) for p, n in _collect(parse_text(viejo_texto)).items()}
    nuevo = {p: (n.kind, n.size) for p, n in _collect(parse_text(nuevo_texto)).items()}
    return detectar_rotacion_share(viejo, nuevo)


def validar_sectores(
    viejo_path: Path, texto_nuevo: str
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """(perdidos, nuevos, rotados) frente al volcado vigente.

    `perdidos` = sectores que hoy traen archivos y el candidato no trae: casi
    siempre significa que las credenciales nuevas no alcanzan los mismos datos
    (share sin montar, cuenta equivocada…) y aplicarlo borraría media biblioteca.
    `rotados` = pérdidas explicadas por una rotación de share (misma biblioteca),
    que sí son legítimas: `main` solo aborta con las pérdidas sin explicar.
    """
    if not viejo_path.exists():
        return [], [], []
    viejo_texto = viejo_path.read_text(encoding="utf-8")
    perdidos, nuevos = validar_sectores_simples(viejo_texto, texto_nuevo)
    return perdidos, nuevos, _rotaciones(viejo_texto, texto_nuevo)


def validar_sectores_simples(viejo_texto: str, texto_nuevo: str) -> tuple[list[str], list[str]]:
    """(perdidos, nuevos) comparando solo las etiquetas de sector con archivos."""
    viejos = sectores_con_archivos(viejo_texto)
    nuevos = sectores_con_archivos(texto_nuevo)
    return sorted(viejos - nuevos), sorted(nuevos - viejos)



def resumen_diff(viejo_path: Path, texto_nuevo: str) -> bool:
    """Imprime el diff vigente → candidato. Devuelve False si procede abortar."""
    if not viejo_path.exists():
        print("   · sin volcado previo: se creará uno nuevo")
        return True
    viejo, nuevo = _rutas(parse_file(viejo_path)), _rutas(parse_text(texto_nuevo))
    fi = {p for p, (k, _) in viejo.items() if k == "file"}
    fj = {p for p, (k, _) in nuevo.items() if k == "file"}
    nuevas, fuera = sorted(fj - fi), sorted(fi - fj)
    distintos = sorted(p for p in fi & fj if viejo[p][1] != nuevo[p][1])
    print(f"   · ficheros: +{len(nuevas)} / -{len(fuera)} / ~{len(distintos)}")
    for p in fuera[:5]:
        print(f"       - {p}")
    for p in nuevas[:5]:
        print(f"       + {p}")
    if len(fuera) > 5 or len(nuevas) > 5:
        print("       (… listado truncado)")
    if fi and not fj:
        print("   ✖ el candidato no trae NINGÚN fichero: se aborta (usa --allow-vacio)")
        return False
    return True


def escribir_en_sitio(path: Path, texto: str) -> None:
    """Escribe EN SITIO (mismo inodo) para que el bind-mount de Docker lo vea.

    `os.replace` cambiaría el inodo y los contenedores seguirían leyendo el
    fichero antiguo. Se construye y valida el texto completo antes de truncar,
    y el guard anti-vaciado de `app.sync` cubre un volcado a medias.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(texto, encoding="utf-8")
    with tmp.open("rb") as origen, path.open("wb") as destino:
        shutil.copyfileobj(origen, destino)
    tmp.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresca el volcado canónico MEGA (mega-ls -R -l)")
    ap.add_argument("--out", default=os.environ.get("MEGA_OUT", str(DUMP_DEFAULT)))
    ap.add_argument("--mega-bin", default=os.environ.get("MEGA_BIN", MEGA_BIN_DEFAULT))
    ap.add_argument("--listings-dir", default=None, help="Directorio para guardar/reusar listados")
    ap.add_argument("--reusar", action="store_true", help="Reutiliza los listados ya existentes")
    ap.add_argument("--timeout", type=int, default=1800, help="Segundos por mega-ls (def. 1800)")
    ap.add_argument("--dry-run", action="store_true", help="No escribe el volcado")
    ap.add_argument("--allow-vacio", action="store_true", help="Permite un volcado sin ficheros")
    ap.add_argument(
        "--permitir-sectores-perdidos",
        action="store_true",
        help="Permite perder sectores con archivos (p. ej. la cuenta nueva no monta "
        "el share): por defecto se aborta para no vaciar media biblioteca",
    )
    ap.add_argument("--no-backup", action="store_true", help="No guarda copia .bak del vigente")
    args = ap.parse_args()

    out = Path(args.out).expanduser().resolve()
    mega_bin = Path(args.mega_bin).expanduser()
    temporales = args.listings_dir is None
    listings_dir = Path(args.listings_dir or tempfile.mkdtemp(prefix="alucard-volcado-")).resolve()

    print("── 1/4 Conexión MEGAcmd ─────────────────────────────────────────────")
    cuenta = cuenta_activa(mega_bin)
    sectores_ = sectores(mega_bin)
    print(f"   cuenta: {cuenta}")
    for titulo, ruta, _ in sectores_:
        print(f"   {titulo:52} ← {ruta}")

    print("── 2/4 Volcado de raíces (mega-ls -R -l) ────────────────────────────")
    listados = volcar_listados(sectores_, mega_bin, listings_dir, args.timeout, reusar=args.reusar)

    print("── 3/4 Construcción y diff ──────────────────────────────────────────")
    texto, total = construir_volcado(sectores_, listados, cuenta)
    print(
        f"   candidato: {total['files']} archivos, {total['folders']} carpetas, "
        f"{human(total['bytes'])}"
    )
    # Rotación de credenciales: la cuenta activa cambia cada semana (y con ella el
    # share montado), pero los datos deben ser LOS MISMOS. Si el candidato pierde
    # sectores que hoy traen archivos, se aborta ANTES de escribir… salvo que la
    # pérdida se explique por una rotación de share (misma biblioteca): en ese caso
    # `app.sync` remapea las rutas y conserva títulos/IGDB.
    perdidos, nuevos, rotados = validar_sectores(out, texto)
    for viejo_sec, nuevo_sec in rotados:
        print(f"   ↻ rotación de share (misma biblioteca): {viejo_sec} → {nuevo_sec}")
    if nuevos:
        print(f"   · AVISO: sectores nuevos frente al vigente: {', '.join(nuevos)}")
    explicados = {v for v, _ in rotados}
    sin_explicar = [p for p in perdidos if p not in explicados]
    if sin_explicar:
        if not args.permitir_sectores_perdidos:
            print("   ✖ el candidato NO trae estos sectores de la biblioteca:")
            for etiqueta in sin_explicar:
                print(f"       - {etiqueta}")
            print("     → ¿credenciales rotadas que no alcanzan los mismos datos? NO se escribe nada.")
            print("     → si la pérdida es intencionada: --permitir-sectores-perdidos")
            return 1
        print(f"   ⚠ pérdida de sectores permitida: {', '.join(sin_explicar)}")
    try:
        procede = resumen_diff(out, texto)
    except ImportError:
        print("   · diff omitido (falta el entorno del backend: `cd backend && uv sync`)")
        procede = True
    if not procede and not args.allow_vacio:
        return 1

    if args.dry_run:
        print(f"── 4/4 Dry-run: no se escribe {out} ({len(texto)} bytes) ───────────")
    else:
        print("── 4/4 Escritura en sitio (mismo inodo para el bind-mount) ──────────")
        if out.exists() and not args.no_backup:
            shutil.copy2(out, out.with_name(f"{out.name}.bak"))
            print(f"   copia previa → {out.name}.bak")
        escribir_en_sitio(out, texto)
        print(f"✔ volcado actualizado: {out} ({len(texto)} bytes)")

    if temporales:
        print(f"   (listados temporales en {listings_dir}; usa --listings-dir para conservarlos)")
    print("   siguiente paso: `app.sync` aplica el diff a la BD (backend-sync lo detecta solo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
