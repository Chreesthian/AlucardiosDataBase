#!/usr/bin/env python3
"""Explora VARIAS cuentas MEGA (rotación semanal) y compara su contenido.

Las credenciales de MEGA rotan semana a semana: cambia la cuenta, pero la
biblioteca (el *in-share*) debería ser la misma. Este diagnóstico responde a la
pregunta inversa a la del pipeline: **¿qué ve cada cuenta y en qué se
complementan?** Sirve para…

  · confirmar que todas las cuentas de la semana montan el mismo share (o
    descubrir cuáles se quedan cortas y NO deben usarse para el volcado),
  · detectar títulos/versiones que solo alcanza una cuenta (contenido que se
    puede completar desde otra),
  · comparar cuotas, nº de *in-shares* y tamaño accesible por cuenta.

QUÉ HACE, por cada cuenta:

  1. Rota la sesión MEGAcmd (conserva la anterior con `--keep-session` y la
     restaura si el login nuevo falla; al terminar deja la sesión preferida).
  2. Recoge `mega-whoami`, `mega-df` (cuota) y `mega-mount` (in-shares).
  3. Vuelca cada raíz con `mega-ls -R -l` a `--listings-dir/<cuenta>/`.
  4. Construye el volcado ASCII canónico (mismo formato que
     `scripts/refrescar_volcado.py`) y lo guarda junto a los listados.
  5. Calcula totales, buckets, títulos (FOLDER de profundidad 2 bajo el bucket)
     y tipos de versión (`B-ASE`/`U-PD`/`D-LC`) reutilizando el código de
     `app.ingest` para no divergir del vocabulario de la BD.

Después compara las cuentas y escribe un informe en JSON + Markdown bajo `data/`
(artefactos generados, nunca versionados).

Uso:
    cd backend && uv run python ../scripts/explorar_cuentas_mega.py \\
        --cuentas ~/.config/alucard/mega_cuentas.txt \\
        --listings-dir ../data/cuentas_mega \\
        --informe ../data/reporte_cuentas_mega.json \\
        --markdown ../data/reporte_cuentas_mega.md

Formato del fichero de cuentas (`--cuentas`, chmod 600, FUERA del repo):

    # una cuenta por línea: email <sep> contraseña
    dts.01.others@gmail.com<TAB>contraseña-1
    dts.02.swch@gmail.com;contraseña-2
    dts.03.swch@gmail.com=contraseña-3

El separador puede ser tabulador, `;`, `,`, `=` o espacio. Las contraseñas NUNCA
se imprimen ni se escriben en los informes.

Variables de entorno:
    MEGA_BIN   binarios MEGAcmd (def. /home/christian/opt/megacmd/usr/bin)
    ALUCARD_MEGA_ENV  fichero de credenciales preferidas (def. ~/.config/alucard/mega.env)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
for _ruta in (str(ROOT), str(BACKEND), str(SCRIPTS)):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

import refrescar_volcado as rv  # noqa: E402  (helpers de sectores/volcado)

from app.ingest import bucket_letter, classify_version  # noqa: E402
from app.parser import parse_text  # noqa: E402
from app.safefs import atomic_write_text  # noqa: E402

MEGA_BIN_DEFAULT = rv.MEGA_BIN_DEFAULT
MEGA_ENV_POR_DEFECTO = Path(
    os.environ.get("ALUCARD_MEGA_ENV", Path.home() / ".config/alucard/mega.env")
)

# Tiempos generosos: un login nuevo descarga el árbol de nodos de la cuenta y el
# `mega-ls -R -l` de un share de varios TiB puede tardar minutos.
T_LOGIN = 600
T_CORTO = 120
T_LISTADO = 3600

_SEP_RE = re.compile(r"[\t;,=]|\s+")
_RE_CUOTA = re.compile(r"USED STORAGE:\s*(\d+)\s+([\d.]+)%\s+of\s+(\d+)")
_RE_SESION = re.compile(r"session is:\s*(\S+)")



def slug_de(email: str) -> str:
    """Nombre de carpeta seguro para una cuenta (`dts.01.others@gmail.com`)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", email.split("@", 1)[0]) or "cuenta"


def leer_cuentas(path: Path) -> list[tuple[str, str]]:
    """[(email, password)] del fichero de cuentas (nunca se imprime la clave)."""
    if not path.is_file():
        raise SystemExit(f"no encuentro el fichero de cuentas: {path}")
    modo = path.stat().st_mode & 0o777
    if modo & 0o077:
        print(
            f"⚠ AVISO: {path} tiene permisos {modo:03o}; debería ser 600 "
            "(chmod 600) para no exponer credenciales.",
            file=sys.stderr,
        )
    cuentas: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for linea in path.read_text(encoding="utf-8").splitlines():
        texto = linea.strip()
        if not texto or texto.startswith("#"):
            continue
        partes = [p for p in _SEP_RE.split(texto, maxsplit=1) if p]
        if len(partes) != 2:
            print(f"⚠ AVISO: línea ignorada (formato no válido): {texto[:12]}…", file=sys.stderr)
            continue
        email, password = partes[0].strip(), partes[1].strip()
        if email.lower() in vistos:
            continue
        vistos.add(email.lower())
        cuentas.append((email, password))
    if not cuentas:
        raise SystemExit(f"sin cuentas válidas en {path}")
    return cuentas


def _mega(args: list[str], mega_bin: Path, timeout: int) -> tuple[int, str]:
    """Ejecuta MEGAcmd y devuelve (rc, stdout+stderr). Nunca incluye credenciales."""
    binario = rv._binario(args[0], mega_bin)
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
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _limpiar(texto: str) -> str:
    """Quita los banners de MEGAcmd para leer la respuesta real."""
    prefijos = ("Initiating MEGAcmd", "Resuming session")
    return "\n".join(
        linea for linea in texto.splitlines() if not linea.strip().startswith(prefijos)
    ).strip()


def cuenta_activa(mega_bin: Path) -> str:
    """Email de la sesión MEGAcmd activa ('' si no hay)."""
    rc, salida = _mega(["mega-whoami"], mega_bin, T_CORTO)
    m = rv._RE_CUENTA.search(salida)
    return m.group(1) if m and rc == 0 else ""


def sesion_activa(mega_bin: Path) -> str:
    """Clave de sesión (para poder retomarla) o '' si no hay login."""
    _, salida = _mega(["mega-session"], mega_bin, T_CORTO)
    m = _RE_SESION.search(salida)
    return m.group(1) if m else ""


def _env_valor(fichero: Path, clave: str) -> str:
    """Valor de una clave en un fichero `.env` (misma semántica que mega_session.sh)."""
    if not fichero.is_file():
        return ""
    patron = re.compile(rf"^[ \t]*{re.escape(clave)}[ \t]*=[ \t]*(.*)$", re.MULTILINE)
    coincidencias = patron.findall(fichero.read_text(encoding="utf-8"))
    return coincidencias[-1].strip().strip('"').strip("'") if coincidencias else ""


def credenciales_preferidas() -> tuple[str, str]:
    """MEGA_EMAIL/MEGA_PASSWORD del fichero preferido (mega.env), si existe."""
    return (
        _env_valor(MEGA_ENV_POR_DEFECTO, "MEGA_EMAIL"),
        _env_valor(MEGA_ENV_POR_DEFECTO, "MEGA_PASSWORD"),
    )


def _parsear_montajes(texto: str) -> list[dict[str, str]]:
    """Montajes de la salida cruda de `mega-mount` (función pura, testeable)."""
    out: list[dict[str, str]] = []
    for linea in texto.splitlines():
        # El nombre del share puede contener espacios (p. ej. "ORTIK 90"): se
        # captura todo hasta el sufijo " (nivel de acceso)" anclado al final.
        m = re.match(
            r"^(?P<etiqueta>\w+)\s+on\s+(?P<ruta>.+?)\s*(?:\((?P<acceso>[^)]+)\))?\s*$",
            linea.strip(),
        )
        if not m:
            continue
        out.append(
            {"tipo": m.group("etiqueta"), "ruta": m.group("ruta"), "acceso": m.group("acceso") or ""}
        )
    return out


def montajes(mega_bin: Path) -> list[dict[str, str]]:
    """Raíces montadas según `mega-mount` (con el nivel de acceso del share)."""
    _, salida = _mega(["mega-mount"], mega_bin, T_CORTO)
    return _parsear_montajes(salida)


def guardar_sesion(mega_bin: Path, email: str, password: str) -> dict[str, str]:
    """Login/rotación hacia `email`, conservando la sesión previa si el login falla."""
    actual = cuenta_activa(mega_bin)
    if actual and actual.lower() == email.lower():
        return {"estado": "reutilizada", "detalle": "la sesión activa ya era de esta cuenta"}
    previa_sesion, previa_cuenta = sesion_activa(mega_bin), actual
    if actual:
        _mega(["mega-logout", "--keep-session"], mega_bin, T_CORTO)
    rc, salida = _mega(["mega-login", email, password], mega_bin, T_LOGIN)
    if cuenta_activa(mega_bin).lower() == email.lower():
        return {"estado": "login", "detalle": f"rotación desde {previa_cuenta or '<ninguna>'}"}
    motivo = _limpiar(salida).splitlines()
    detalle = motivo[0] if motivo else f"rc={rc}"
    if previa_sesion and not cuenta_activa(mega_bin):
        _mega(["mega-login", previa_sesion], mega_bin, T_LOGIN)
    return {
        "estado": "error",
        "detalle": f"login fallido ({detalle}); sesión restaurada: {cuenta_activa(mega_bin) or '<ninguna>'}",
    }


def sectores_de(mega_bin: Path) -> list[tuple[str, str, str]]:
    """[(título de sector, ruta MEGA, etiqueta [ROOT])] de la cuenta activa."""
    out = list(rv.RAICES_FIJAS)
    for montaje in montajes(mega_bin):
        if montaje["tipo"].upper() != "INSHARE":
            continue
        ruta = montaje["ruta"]
        out.append((rv.etiqueta_sector(ruta), ruta, ruta))
    return out


def _archivos_bajo(nodo, prefijo: str, acc: dict[str, int]) -> None:
    """Acumula {ruta_relativa: bytes} de todos los ficheros del subárbol."""
    for hijo in nodo.children:
        ruta = f"{prefijo}/{hijo.name}" if prefijo else hijo.name
        if hijo.is_folder:
            _archivos_bajo(hijo, ruta, acc)
        else:
            acc[ruta] = hijo.size


def estadisticas(texto: str) -> dict:
    """Totales, buckets y títulos (FOLDER d2) del volcado de una cuenta.

    Los títulos se indexan por `bucket/título` (mismo prefijo que usa
    `app.novedades.titulo_de`) para poder compararlos entre cuentas aunque el
    *in-share* tenga otro dueño. Las estructuras internas van con prefijo `_`.
    """
    dump = parse_text(texto)
    sectores: list[dict] = []
    titulos: dict[str, dict] = {}
    for sec in dump.sectors:
        info = {
            "sector": sec.label,
            "files": 0,
            "folders": 0,
            "bytes": 0,
            "buckets": [],
            "titulos": 0,
        }
        for root in sec.roots:
            info["files"] += root.total_files
            info["folders"] += root.total_folders
            info["bytes"] += root.total_size
            for bucket in root.children:
                if not bucket.is_folder:
                    continue
                if bucket.name not in info["buckets"]:
                    info["buckets"].append(bucket.name)
                for titulo in bucket.children:
                    if not titulo.is_folder:
                        continue
                    info["titulos"] += 1
                    clave = f"{bucket.name}/{titulo.name}"
                    entrada = titulos.setdefault(
                        clave,
                        {
                            "clave": clave,
                            "titulo": titulo.name,
                            "bucket": bucket.name,
                            "letra": bucket_letter(bucket.name),
                            "_sectores": set(),
                            "_versiones": set(),
                            "_archivos": {},
                            "bytes": 0,
                            "tipos": {},
                        },
                    )
                    entrada["_sectores"].add(sec.label)
                    entrada["bytes"] = max(entrada["bytes"], titulo.total_size)
                    for version in titulo.children:
                        if version.is_folder:
                            entrada["_versiones"].add(version.name)
                            tipo = classify_version(version.name)
                            entrada["tipos"][tipo] = entrada["tipos"].get(tipo, 0) + 1
                        else:  # fichero suelto dentro del título
                            entrada["_archivos"][version.name] = version.size
                            entrada["tipos"]["other"] = entrada["tipos"].get("other", 0) + 1
                    _archivos_bajo(titulo, "", entrada["_archivos"])
        sectores.append(info)
    return {
        "sectores": sectores,
        "titulos_n": len(titulos),
        "letras": sorted({t["letra"] for t in titulos.values()}),
        "_titulos": titulos,
    }


def explorar_cuenta(
    mega_bin: Path,
    email: str,
    password: str,
    listings_root: Path,
    timeout: int,
    *,
    reusar: bool = False,
) -> dict:
    """Sesión + cuota + montajes + volcado completo de una cuenta."""
    inicio = datetime.datetime.now(datetime.UTC)
    slug = slug_de(email)
    destino = listings_root / slug
    destino.mkdir(parents=True, exist_ok=True)
    print(f"── {email} ──────────────────────────────────────────────", flush=True)
    salida: dict = {
        "email": email,
        "slug": slug,
        "carpeta": str(destino),
        "inicio": inicio.isoformat(timespec="seconds"),
        "fin": None,
        "ok": False,
        "error": None,
    }
    sesion = guardar_sesion(mega_bin, email, password)
    salida["sesion"] = sesion
    print(f"   sesión: {sesion['estado']} ({sesion['detalle']})", flush=True)
    if sesion["estado"] == "error":
        salida["error"] = sesion["detalle"]
        return salida

    salida["cuenta_activa"] = cuenta_activa(mega_bin)
    salida["montajes"] = montajes(mega_bin)
    _, df = _mega(["mega-df"], mega_bin, T_CORTO)
    salida["df"] = _limpiar(df)
    m = _RE_CUOTA.search(df)
    if m:
        salida["cuota"] = {
            "usado_bytes": int(m.group(1)),
            "pct": float(m.group(2)),
            "total_bytes": int(m.group(3)),
        }
    sectores_ = sectores_de(mega_bin)
    salida["sectores_declarados"] = [{"sector": t, "ruta": r} for t, r, _ in sectores_]
    print(f"   sectores: {len(sectores_)} → {', '.join(t for t, _, _ in sectores_)}", flush=True)

    try:
        listados = rv.volcar_listados(sectores_, mega_bin, destino, timeout, reusar=reusar)
        texto, total = rv.construir_volcado(sectores_, listados, salida["cuenta_activa"] or email)
    except SystemExit as exc:  # MEGAcmd sin salida: se registra y se sigue con las demás
        salida["error"] = str(exc)
        return salida

    volcado = destino / f"volcado_{slug}.txt"
    atomic_write_text(volcado, texto)
    salida["volcado"] = str(volcado)
    salida["totales"] = total
    salida.update(estadisticas(texto))
    salida["ok"] = True
    salida["fin"] = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    print(
        f"   ✔ {total['files']} archivos / {total['folders']} carpetas / "
        f"{rv.human(total['bytes'])} · {salida['titulos_n']} títulos",
        flush=True,
    )
    return salida


CAP_MUESTRA = 300


def vista(cuenta: dict) -> dict:
    """Versión serializable de una cuenta (sin las estructuras internas `_`)."""
    titulos = cuenta.get("_titulos", {})
    out = {k: v for k, v in cuenta.items() if not k.startswith("_")}
    letras: dict[str, int] = {}
    for entrada in titulos.values():
        letras[entrada["letra"]] = letras.get(entrada["letra"], 0) + 1
    out["titulos_por_letra"] = dict(sorted(letras.items()))
    out["titulos_claves"] = sorted(titulos)
    return out


def _shares_con_archivos(sectores: list[dict]) -> tuple[str, ...]:
    """Etiquetas de *in-share* que aportan archivos = identidad de la biblioteca.

    Misma idea que `refrescar_volcado.sectores_con_archivos`: la etiqueta la fija
    `app.parser` a partir del share montado (`INSHARE <dueño>:<carpeta>`), así que
    es estable aunque la cuenta (y su Cloud Drive privado) cambie.
    """
    return tuple(
        sorted(
            s["sector"]
            for s in sectores
            if s.get("files", 0) > 0 and s["sector"].startswith("INSHARE ")
        )
    )


def _comparar_biblioteca(miembros: list[dict], vigente: dict | None) -> dict:
    """Cobertura, exclusivos y complementos DENTRO de una misma biblioteca."""
    por_cuenta = {c["email"]: c.get("_titulos", {}) for c in miembros}
    union: set[str] = set()
    for titulos in por_cuenta.values():
        union |= set(titulos)
    indice = {clave: sorted(e for e, t in por_cuenta.items() if clave in t) for clave in union}

    cobertura = []
    for email, titulos in por_cuenta.items():
        faltan = sorted(union - set(titulos))
        cobertura.append(
            {
                "email": email,
                "titulos": len(titulos),
                "pct_titulos_union": round(100.0 * len(titulos) / len(union), 2) if union else 0.0,
                "titulos_que_faltan": len(faltan),
                "ejemplos_faltan": faltan[:15],
            }
        )
    cobertura.sort(key=lambda c: (-c["titulos"], c["email"]))

    exclusivos = {email: sorted(c for c in union if indice[c] == [email]) for email in por_cuenta}
    parciales: list[dict] = []
    for clave in sorted(union):
        implicadas = indice[clave]
        if len(implicadas) < 2:
            continue
        conjuntos = {e: set(por_cuenta[e][clave]["_archivos"]) for e in implicadas}
        if len({frozenset(v) for v in conjuntos.values()}) == 1:
            continue  # mismo contenido exacto en todas
        archivos_union = set().union(*conjuntos.values())
        detalle = {}
        for email in implicadas:
            faltan = sorted(archivos_union - conjuntos[email])
            detalle[email] = {
                "archivos": len(conjuntos[email]),
                "bytes": por_cuenta[email][clave]["bytes"],
                "faltan": len(faltan),
                "faltan_muestra": faltan[:10],
                "versiones": sorted(por_cuenta[email][clave]["_versiones"]),
            }
        referencia = por_cuenta[implicadas[0]][clave]
        parciales.append(
            {
                "clave": clave,
                "titulo": referencia["titulo"],
                "letra": referencia["letra"],
                "cuentas": detalle,
            }
        )
    parciales.sort(key=lambda p: (-min(c["faltan"] for c in p["cuentas"].values()), p["clave"]))

    grupo: dict = {
        "cuentas": [c["email"] for c in miembros],
        "titulos_union": len(union),
        "titulos_en_todas": sum(1 for c in union if len(indice[c]) == len(por_cuenta)),
        "cobertura": cobertura,
        "cuentas_completas": [c["email"] for c in cobertura if c["titulos_que_faltan"] == 0],
        "titulos_exclusivos": {e: v for e, v in exclusivos.items() if v},
        "parciales_total": len(parciales),
        "parciales_muestra": parciales[:CAP_MUESTRA],
        "vs_volcado_vigente": None,
    }
    if vigente is not None:
        claves_vig = set(vigente["_titulos"])
        aportan = sorted(union - claves_vig)
        perderian = sorted(claves_vig - union)
        grupo["vs_volcado_vigente"] = {
            "titulos_en_vigente": len(claves_vig),
            "titulos_que_aportarian_las_cuentas": len(aportan),
            "ejemplos_aportarian": aportan[:30],
            "aportarian_por_letra": _por_letra(aportan),
            "titulos_del_vigente_que_ninguna_cuenta_alcanza": len(perderian),
            "ejemplos_perderian": perderian[:30],
        }
    return grupo


def comparar(cuentas: list[dict], vigente_texto: str | None) -> dict:
    """Compara las cuentas AGRUPADAS por biblioteca (in-shares con archivos).

    Cuentas que montan bibliotecas distintas no se mezclan entre sí: los títulos
    de un share retro no deben contarse como títulos Switch "que faltan".
    """
    ok = [c for c in cuentas if c.get("ok")]
    vigente = estadisticas(vigente_texto) if vigente_texto else None
    clave_vigente = _shares_con_archivos(vigente["sectores"]) if vigente else ()

    grupos: dict[tuple[str, ...], list[dict]] = {}
    for cuenta in ok:
        grupos.setdefault(_shares_con_archivos(cuenta.get("sectores", [])), []).append(cuenta)

    bibliotecas: list[dict] = []
    for clave, miembros in sorted(grupos.items(), key=lambda kv: (kv[0] != clave_vigente, kv[0])):
        es_canonica = bool(clave) and clave == clave_vigente
        grupo = _comparar_biblioteca(miembros, vigente if es_canonica else None)
        grupo["clave"] = list(clave)
        grupo["etiqueta"] = ", ".join(clave) if clave else "(sin in-share con archivos)"
        grupo["es_canonica"] = es_canonica
        grupo["intercambiables"] = len(miembros) > 1 and len(grupo["cuentas_completas"]) == len(miembros)
        bibliotecas.append(grupo)

    return {
        "cuentas_escaneadas": len(cuentas),
        "cuentas_ok": len(ok),
        "biblioteca_canonica": ", ".join(clave_vigente) if clave_vigente else None,
        "bibliotecas": bibliotecas,
    }



def _por_letra(claves: list[str]) -> dict[str, int]:
    """{letra: nº de títulos} de claves `bucket/título`."""
    conteo: dict[str, int] = {}
    for clave in claves:
        letra = bucket_letter(clave.split("/", 1)[0])
        conteo[letra] = conteo.get(letra, 0) + 1
    return dict(sorted(conteo.items()))


def _celda(texto: str) -> str:
    return texto.replace("|", "/")


def informe_markdown(informe: dict) -> str:
    """Informe legible (Markdown) del JSON de comparación."""
    comp = informe["comparacion"]
    bibliotecas = comp.get("bibliotecas", [])
    por_email: dict[str, tuple[str, dict]] = {}
    for grupo in bibliotecas:
        for cub in grupo.get("cobertura", []):
            por_email[cub["email"]] = (grupo["etiqueta"], cub)
    lineas: list[str] = [
        "# Reporte de cuentas MEGA (comparativa)",
        "",
        f"- Generado: `{informe['generado_en']}`",
        f"- Herramienta: {informe['herramienta']}",
        f"- Cuentas exploradas: {comp['cuentas_escaneadas']} (con datos: {comp['cuentas_ok']})",
        f"- Volcado vigente comparado: `{informe.get('volcado_vigente') or '(ninguno)'}`",
        f"- Biblioteca canónica (la del volcado vigente): "
        f"`{comp.get('biblioteca_canonica') or '(desconocida)'}`",
        "",
        "## 1. Resumen por cuenta",
        "",
        "| Cuenta | Sesión | In-shares | Archivos | Carpetas | Tamaño | Títulos | % de su biblioteca |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cuenta in informe["cuentas"]:
        email = cuenta["email"]
        if not cuenta["ok"]:
            lineas.append(
                f"| `{email}` | ✖ {_celda(cuenta['sesion']['detalle'])} | — | — | — | — | — | — |"
            )
            continue
        compartidos = [
            m["ruta"] for m in cuenta.get("montajes", []) if m["tipo"].upper() == "INSHARE"
        ]
        cub = por_email.get(email, ("", {}))[1]
        lineas.append(
            f"| `{email}` | {cuenta['sesion']['estado']} | {len(compartidos)} "
            f"| {cuenta['totales']['files']} | {cuenta['totales']['folders']} "
            f"| {rv.human(cuenta['totales']['bytes'])} | {cuenta['titulos_n']} "
            f"| {cub.get('pct_titulos_union', 0)} % |"
        )

    lineas += ["", "## 2. In-shares y cuota", ""]
    for cuenta in informe["cuentas"]:
        if not cuenta["ok"]:
            continue
        cuota = cuenta.get("cuota", {})
        lineas.append(f"### `{cuenta['email']}`")
        for montaje in cuenta.get("montajes", []):
            acceso = f" ({montaje['acceso']})" if montaje.get("acceso") else ""
            lineas.append(f"- `{montaje['tipo']}` → `{montaje['ruta']}`{acceso}")
        if cuota:
            lineas.append(
                f"- Cuota: {rv.human(cuota['usado_bytes'])} usados de "
                f"{rv.human(cuota['total_bytes'])} ({cuota['pct']} %)"
            )
        lineas.append(
            "- Títulos por letra: "
            + ", ".join(f"{k}={v}" for k, v in cuenta.get("titulos_por_letra", {}).items())
        )
        lineas.append(f"- Volcado propio: `{cuenta.get('volcado')}`")
        lineas.append("")

    lineas += ["## 3. Bibliotecas detectadas", ""]
    if not bibliotecas:
        lineas.append("Ninguna cuenta aportó datos.")
    for grupo in bibliotecas:
        marca = "⭐ CANÓNICA" if grupo["es_canonica"] else "— otra biblioteca"
        comp_ = "sí" if grupo["intercambiables"] else "NO"
        lineas += [
            f"### {marca}: `{grupo['etiqueta']}`",
            "",
            f"- Cuentas: {', '.join(f'`{e}`' for e in grupo['cuentas'])}",
            f"- Títulos distintos: **{grupo['titulos_union']}** "
            f"(en todas las cuentas: {grupo['titulos_en_todas']})",
            f"- ¿Cuentas intercambiables entre sí?: **{comp_}**",
            "",
        ]
        for cub in grupo.get("cobertura", []):
            lineas.append(
                f"- `{cub['email']}`: {cub['titulos']} títulos "
                f"({cub['pct_titulos_union']} %), le faltan {cub['titulos_que_faltan']}"
                + (
                    f" (p. ej. {', '.join(_celda(c) for c in cub['ejemplos_faltan'][:3])})"
                    if cub["ejemplos_faltan"]
                    else ""
                )
            )
        exclusivos = grupo.get("titulos_exclusivos", {})
        if exclusivos:
            lineas += ["", "Títulos que SOLO ve una cuenta:", ""]
            for email, claves in exclusivos.items():
                lineas.append(
                    f"- `{email}`: {len(claves)} → {', '.join(_celda(c) for c in claves[:15])}"
                )
        elif len(grupo["cuentas"]) > 1:
            lineas += ["", "Sin títulos exclusivos: todas las cuentas ven el mismo catálogo."]
        lineas.append("")

    lineas += ["## 4. Complementos (mismo título, contenido distinto)", ""]
    con_parciales = [g for g in bibliotecas if g.get("parciales_total")]
    if not con_parciales:
        lineas.append("Ningún título con contenido distinto entre cuentas de la misma biblioteca.")
    for grupo in con_parciales:
        lineas += [
            f"### `{grupo['etiqueta']}` — {grupo['parciales_total']} títulos",
            "",
        ]
        for parcial in grupo.get("parciales_muestra", [])[:20]:
            lineas.append(f"#### {_celda(parcial['clave'])}")
            for email, detalle in parcial["cuentas"].items():
                muestra = ", ".join(_celda(f) for f in detalle["faltan_muestra"][:3]) or "—"
                lineas.append(
                    f"- `{email}`: {detalle['archivos']} archivos, {rv.human(detalle['bytes'])}, "
                    f"faltan {detalle['faltan']} ({muestra})"
                )
            lineas.append("")
    lineas.append("")

    lineas += ["## 5. Frente al volcado canónico vigente", ""]
    con_vigente = [g for g in bibliotecas if g.get("vs_volcado_vigente")]
    if not con_vigente:
        lineas.append(
            "Ninguna cuenta monta la misma biblioteca que el volcado vigente "
            f"(`{comp.get('biblioteca_canonica')}`): comparar produciría conclusiones falsas."
        )
    for grupo in con_vigente:
        vig = grupo["vs_volcado_vigente"]
        lineas += [
            "",
            f"### `{grupo['etiqueta']}`",
            "",
            f"- Títulos en el volcado vigente: **{vig['titulos_en_vigente']}**",
            f"- Títulos que aportarían las cuentas y NO están en el vigente: "
            f"**{vig['titulos_que_aportarian_las_cuentas']}**",
            f"- Títulos del vigente que ninguna cuenta alcanza ahora: "
            f"**{vig['titulos_del_vigente_que_ninguna_cuenta_alcanza']}**",
        ]
        if vig["ejemplos_aportarian"]:
            lineas.append(
                "- Ejemplos a aportar: "
                + ", ".join(_celda(c) for c in vig["ejemplos_aportarian"][:15])
            )
        if vig["ejemplos_perderian"]:
            lineas.append(
                "- Ejemplos que se perderían: "
                + ", ".join(_celda(c) for c in vig["ejemplos_perderian"][:15])
            )
    lineas.append("")

    lineas += ["## 6. Conclusión", ""]
    for texto in informe.get("recomendacion", []):
        lineas.append(f"- {texto}")
    lineas.append("")
    return "\n".join(lineas)


def recomendacion(cuentas: list[dict], comp: dict) -> list[str]:
    """Conclusiones accionables: qué cuenta usar como fuente y qué falta."""
    textos: list[str] = []
    for cuenta in cuentas:
        if not cuenta.get("ok"):
            textos.append(f"Sin datos de `{cuenta['email']}`: {cuenta['error']}")

    bibliotecas = comp.get("bibliotecas", [])
    canonicas = [g for g in bibliotecas if g["es_canonica"]]
    for grupo in canonicas:
        cuentas_txt = ", ".join(f"`{e}`" for e in grupo["cuentas"])
        if grupo["intercambiables"]:
            textos.append(
                f"Biblioteca canónica `{grupo['etiqueta']}`: {cuentas_txt} alcanzan los MISMOS "
                f"{grupo['titulos_union']} títulos → rotación segura, cualquiera sirve para "
                "`make volcado-cron`."
            )
        else:
            completas = ", ".join(f"`{e}`" for e in grupo["cuentas_completas"]) or "(ninguna)"
            incompletas = ", ".join(
                f"`{c['email']}` ({c['titulos_que_faltan']} menos)"
                for c in grupo["cobertura"]
                if c["titulos_que_faltan"]
            )
            textos.append(
                f"Biblioteca canónica `{grupo['etiqueta']}`: solo {completas} cubre el 100 % "
                f"({grupo['titulos_union']} títulos)."
            )
            if incompletas:
                textos.append(f"NO usar en solitario para el volcado: {incompletas}.")
        if grupo["parciales_total"]:
            textos.append(
                f"{grupo['parciales_total']} títulos de esa biblioteca tienen contenido distinto "
                "entre esas cuentas: se pueden COMPLEMENTAR (sección 4 / `parciales_muestra`)."
            )
        vig = grupo["vs_volcado_vigente"]
        if vig:
            if vig["titulos_que_aportarian_las_cuentas"]:
                textos.append(
                    f"{vig['titulos_que_aportarian_las_cuentas']} títulos de la biblioteca canónica "
                    "NO están en el volcado vigente: refresca el volcado y `make sync` los incorporará."
                )
            else:
                textos.append("El volcado canónico ya cubre todos los títulos de esa biblioteca.")
            if vig["titulos_del_vigente_que_ninguna_cuenta_alcanza"]:
                textos.append(
                    f"OJO: {vig['titulos_del_vigente_que_ninguna_cuenta_alcanza']} títulos del "
                    "volcado vigente no los ve ninguna cuenta (posible retirada del share)."
                )

    for grupo in bibliotecas:
        if grupo["es_canonica"]:
            continue
        cuentas_txt = ", ".join(f"`{e}`" for e in grupo["cuentas"])
        textos.append(
            f"`{grupo['etiqueta']}` es OTRA biblioteca, montada por {cuentas_txt}: "
            f"{grupo['titulos_union']} títulos de una colección distinta "
            f"({rv.human(sum(c.get('totales', {}).get('bytes', 0) for c in cuentas if c['email'] in grupo['cuentas']))}). "
            "No mezclar con el volcado canónico: si esas credenciales se usaran para "
            "`make volcado-cron`, la guardia de sectores abortaría el refresco."
        )

    if bibliotecas and not canonicas:
        textos.append(
            "Ninguna cuenta monta la biblioteca del volcado vigente: el refresco con estas "
            "credenciales NO debe aplicarse."
        )
    if not bibliotecas:
        textos.append("No hay datos utilizables: revisa credenciales y sesiones de MEGAcmd.")
    return textos


def restaurar_preferida(mega_bin: Path, *, quiet: bool = False) -> None:
    """Deja el host con la sesión de las credenciales preferidas (`mega.env`)."""
    email, password = credenciales_preferidas()
    actual = cuenta_activa(mega_bin)
    if not email:
        if not quiet:
            print(
                f"   · sin credenciales preferidas; se deja la sesión: {actual or '<ninguna>'}",
                flush=True,
            )
        return
    if actual.lower() == email.lower():
        if not quiet:
            print(f"   · sesión final: {actual}", flush=True)
        return
    res = guardar_sesion(mega_bin, email, password)
    if not quiet:
        print(f"   · restauración de sesión: {res['estado']} ({res['detalle']})", flush=True)


def _guardar(informe_path: Path, informe: dict) -> None:
    atomic_write_text(informe_path, json.dumps(informe, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Explora varias cuentas MEGA (rotación semanal) y compara su contenido"
    )
    ap.add_argument(
        "--cuentas",
        default=str(Path.home() / ".config/alucard/mega_cuentas.txt"),
        help="fichero `email<sep>password` (chmod 600), fuera del repo",
    )
    ap.add_argument("--listings-dir", default=str(ROOT / "data/cuentas_mega"))
    ap.add_argument("--informe", default=str(ROOT / "data/reporte_cuentas_mega.json"))
    ap.add_argument("--markdown", default=str(ROOT / "data/reporte_cuentas_mega.md"))
    ap.add_argument("--mega-bin", default=os.environ.get("MEGA_BIN", MEGA_BIN_DEFAULT))
    ap.add_argument("--timeout", type=int, default=T_LISTADO, help="timeout de cada mega-ls (s)")
    ap.add_argument("--reusar", action="store_true", help="reutiliza listados ya volcados por cuenta")
    ap.add_argument(
        "--volcado-vigente",
        default=str(ROOT / "mega_cuenta_contenido_MEGAcmd.txt"),
        help="volcado canónico con el que comparar ('' para desactivar)",
    )
    ap.add_argument("--no-restaurar", action="store_true", help="no vuelve a la sesión preferida")
    args = ap.parse_args()

    mega_bin = Path(args.mega_bin).expanduser()
    if not (mega_bin / "mega-cmd").is_file():
        raise SystemExit(f"MEGAcmd no disponible en {mega_bin} (usa --mega-bin o MEGA_BIN)")
    cuentas_path = Path(args.cuentas).expanduser()
    cuentas = leer_cuentas(cuentas_path)
    listings_root = Path(args.listings_dir).expanduser().resolve()
    informe_path = Path(args.informe).expanduser().resolve()
    md_path = Path(args.markdown).expanduser().resolve()
    vigente_path = Path(args.volcado_vigente).expanduser() if args.volcado_vigente else None

    print(f"Explorando {len(cuentas)} cuentas: {', '.join(e for e, _ in cuentas)}", flush=True)
    resultados: list[dict] = []
    for email, password in cuentas:
        resultados.append(explorar_cuenta(mega_bin, email, password, listings_root, args.timeout, reusar=args.reusar))
        _guardar(  # informe parcial: inspeccionable aunque el proceso siga en marcha
            informe_path,
            {
                "generado_en": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
                "parcial": True,
                "cuentas": [vista(r) for r in resultados],
            },
        )

    vigente_texto = None
    if vigente_path and vigente_path.is_file():
        vigente_texto = vigente_path.read_text(encoding="utf-8")
    comp = comparar(resultados, vigente_texto)
    informe = {
        "generado_en": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "herramienta": "MEGAcmd (mega-ls -R -l) + scripts/explorar_cuentas_mega.py",
        "fichero_cuentas": str(cuentas_path),
        "volcado_vigente": str(vigente_path) if vigente_texto else None,
        "cuentas": [vista(r) for r in resultados],
        "comparacion": comp,
    }
    informe["recomendacion"] = recomendacion(resultados, comp)
    _guardar(informe_path, informe)
    atomic_write_text(md_path, informe_markdown(informe))
    print(f"\n✔ informe: {informe_path}\n✔ informe legible: {md_path}\n", flush=True)
    print(informe_markdown(informe), flush=True)

    if not args.no_restaurar:
        restaurar_preferida(mega_bin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
