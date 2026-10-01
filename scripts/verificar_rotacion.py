#!/usr/bin/env python3
"""Pre-vuelo de rotación MEGA: ¿la cuenta de la semana ve LA MISMA biblioteca?

Se ejecuta ANTES de `refrescar_volcado.py` (`scripts/autovolcado.sh`, por tanto
también en `make volcado-cron`) y NO toca el volcado: solo comprueba que la
sesión activa monta el *in-share* del volcado vigente y que su raíz conserva los
buckets conocidos.

¿Por qué hace falta si `refrescar_volcado` ya tiene guardias?

  · La guardia de sectores aborta, sí… pero DESPUÉS de listar el árbol entero:
    con credenciales que montan otra biblioteca (p. ej. un share de ROMs retro)
    eso son minutos de `mega-ls -R -l` listando TiB que no sirven para nada.
  · El mensaje habla de "sectores perdidos", no de credenciales: el operador no
    ve que el problema es la cuenta de la semana.

Aquí el coste es un `mega-mount` + un `mega-ls` NO recursivo de la raíz (segundos)
y el diagnóstico dice explícitamente qué in-share falta y qué buckets no se ven.

El resultado se escribe en `data/estado_cuentas.json` (átomo) para que la API lo
publique en `GET /api/sync/cuentas` y la UI pueda avisar. Incluye, además, las
entradas de la NUBE PERSONAL de la cuenta (`mega-ls /`, no recursivo): rotan con
las credenciales y NO entran al catálogo (`app.sync` indexa solo la biblioteca),
pero explican por qué los totales del volcado completo no cuadran con los del
catálogo.

FAILOVER DEL POOL (`--elegir-cuenta`): el login y la biblioteca son dos preguntas
distintas. El failover de `lib/mega_session.sh` responde «¿entra esta cuenta?»,
pero una cuenta puede entrar y montar OTRO share (el caso real: una cuenta de ROMs
retro en el pool). Sin este modo, esa credencial deja el pipeline en rc=8 cada 6 h
esperando a un humano aunque en el pool haya otra cuenta que sí ve la biblioteca.

Con `--elegir-cuenta` se prueban las cuentas del pool una a una (segundos por
cuenta: `mega-mount` + un `mega-ls` NO recursivo) y la sesión se queda en la
primera que ve la biblioteca del volcado; si ninguna la ve, se restaura la sesión
de las credenciales preferidas y se sale rc=8 como siempre. El informe final pasa a
ser el de la cuenta elegida y lleva el rastro del proceso (`candidatas`, `inicial`).
`--guardar-elegida` persiste además esa cuenta como credencial preferida (chmod
600, fuera del repo) para que el cron no repita la búsqueda.

Códigos de salida: 0 ok (o forzado con --permitir-otra-biblioteca) · 4 sin sesión
MEGAcmd · 8 la sesión no ve la biblioteca del volcado (NO apliques el volcado).

Uso:
    cd backend && uv run python ../scripts/verificar_rotacion.py
    ... --permitir-otra-biblioteca   # deja pasar (vaciado consciente de la BD)
    ... --elegir-cuenta              # failover: elige del pool la cuenta que la ve
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
for _ruta in (str(ROOT), str(BACKEND), str(SCRIPTS)):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

import explorar_cuentas_mega as ex  # noqa: E402  (mega-* + estadísticas del volcado)
import refrescar_volcado as rv  # noqa: E402  (etiqueta_sector, rutas, binarios)

from app.safefs import atomic_write_text  # noqa: E402

EXIT_OK = 0
EXIT_SIN_SESION = 4
EXIT_BIBLIOTECA_DISTINTA = 8

ESTADO_POR_DEFECTO = ROOT / "data" / "estado_cuentas.json"
VOLCADO_POR_DEFECTO = ROOT / "mega_cuenta_contenido_MEGAcmd.txt"
# Pool de cuentas de la rotación y credencial preferida: FUERA del repo (chmod 600).
MEGA_CUENTAS_POR_DEFECTO = Path(
    os.environ.get("ALUCARD_MEGA_CUENTAS", "~/.config/alucard/mega_cuentas.txt")
).expanduser()
MEGA_ENV_POR_DEFECTO = Path(
    os.environ.get("ALUCARD_MEGA_ENV", "~/.config/alucard/mega.env")
).expanduser()
HERRAMIENTA = "scripts/verificar_rotacion.py (mega-mount + mega-ls, sin listar el árbol)"
HERRAMIENTA_POOL = "scripts/verificar_rotacion.py --elegir-cuenta (pre-vuelo por cuenta del pool)"
ESPERADO_VACIO: dict = {"etiquetas": [], "rutas": [], "buckets": {}, "titulos": 0, "files": 0}
T_LISTADO = 300  # la raíz del share, no el árbol: segundos, no minutos
# Carpetas internas de MEGAcmd en la nube: no son contenido del operador.
NUBE_INTERNA = ("S4 Object storage",)
NUBE_NOMBRES = 10  # nombres que se guardan en el informe (el resto, solo contados)


def _normalizar(nombre: str) -> str:
    return nombre.strip().rstrip("/")


def nube_propia(listado: list[str], *, interno: Iterable[str] = ()) -> dict:
    """Entradas propias de la cuenta en su nube personal (`mega-ls /`, no recursivo).

    Las credenciales MEGA rotan cada semana y la nube personal de la cuenta (la
    que no es el in-share de la biblioteca) cambia con ellas. Esas carpetas NO
    entran al catálogo —`app.sync` indexa solo los sectores de la biblioteca—,
    pero el dato explica al operador por qué los totales del volcado completo no
    cuadran con los del catálogo. Función pura para poder probarla sin MEGAcmd.
    """
    ignorar = {n.strip().lower() for n in interno}
    nombres = [n for n in listado if n.strip().lower() not in ignorar]
    return {"entradas": len(nombres), "nombres": nombres[:NUBE_NOMBRES]}


def parsear_listado_raiz(texto: str) -> list[str]:
    """Nombres de las entradas de la raíz de un share (`mega-ls` NO recursivo).

    MEGAcmd imprime una cabecera con la ruta (`//from/…:BCKP2/: `) y después un
    nombre por línea, sin sufijo para las carpetas. La función es pura para poder
    probarla sin sesión MEGAcmd.
    """
    nombres: list[str] = []
    for linea in texto.splitlines():
        limpio = linea.strip()
        if not limpio or limpio.startswith("//") or limpio.endswith(":"):
            continue  # cabecera, ecos de ruta o banners
        nombres.append(_normalizar(limpio))
    return nombres


def ruta_de_etiqueta(etiqueta: str) -> str | None:
    """`INSHARE dueño:carpeta` → `//from/dueño:carpeta` (None si no es un in-share)."""
    prefijo = "INSHARE "
    if not etiqueta.startswith(prefijo):
        return None
    resto = etiqueta[len(prefijo) :].strip()
    return f"//from/{resto}" if resto else None


def esperado_del_volcado(texto: str) -> dict:
    """Biblioteca canónica del volcado vigente: in-shares, rutas, buckets y totales.

    La identidad es el SHARE (`INSHARE dueño:carpeta`), no la cuenta activa: las
    credenciales rotan cada semana y la etiqueta debe sobrevivir a la rotación.
    """
    stats = ex.estadisticas(texto)
    canonicos = [
        s
        for s in stats["sectores"]
        if s.get("files", 0) > 0 and str(s["sector"]).startswith("INSHARE ")
    ]
    rutas = [r for r in (ruta_de_etiqueta(s["sector"]) for s in canonicos) if r]
    return {
        "etiquetas": [s["sector"] for s in canonicos],
        "rutas": rutas,
        "buckets": {s["sector"]: sorted(s["buckets"]) for s in canonicos},
        "titulos": sum(s.get("titulos", 0) for s in canonicos),
        "files": sum(s.get("files", 0) for s in canonicos),
    }


def evaluar(esperado: dict, montados: set[str] | list[str], listados: dict[str, list[str]]) -> dict:
    """Veredicto PURO: ¿la sesión activa ve la biblioteca del volcado vigente?

    `montados` = rutas de los in-shares de `mega-mount`; `listados` = {ruta: nombres
    de la raíz} de las rutas que se han podido listar. Sin biblioteca canónica
    (volcado de arranque o sin in-shares) no hay nada que verificar y no se bloquea.
    """
    vistos = {str(p).lower() for p in montados}
    faltan_rutas = [r for r in esperado["rutas"] if r.lower() not in vistos]
    faltan_buckets: dict[str, list[str]] = {}
    for ruta, etiqueta in zip(esperado["rutas"], esperado["etiquetas"], strict=True):
        nombres = listados.get(ruta)
        if nombres is None:
            continue  # no montado: ya lo reporta `faltan_rutas`
        vistos_raiz = {_normalizar(n).lower() for n in nombres}
        ausentes = [
            b for b in esperado["buckets"].get(etiqueta, []) if b.lower() not in vistos_raiz
        ]
        if ausentes:
            faltan_buckets[ruta] = ausentes

    if not esperado["rutas"]:
        return {
            "ok": True,
            "causa": "sin_biblioteca_canonica",
            "faltan_rutas": [],
            "faltan_buckets": {},
            "veredicto": "el volcado vigente no declara in-shares con archivos; nada que verificar",
        }

    if faltan_rutas:
        return {
            "ok": False,
            "causa": "inshare_ausente",
            "faltan_rutas": faltan_rutas,
            "faltan_buckets": faltan_buckets,
            "veredicto": "la sesión de MEGAcmd NO monta el in-share de la biblioteca: "
            + ", ".join(faltan_rutas)
            + " (¿credenciales de otra cuenta u otro share?)",
        }

    if faltan_buckets:
        ruta, ausentes = next(iter(faltan_buckets.items()))
        return {
            "ok": False,
            "causa": "buckets_ausentes",
            "faltan_rutas": [],
            "faltan_buckets": faltan_buckets,
            "veredicto": f"la raíz de {ruta} no muestra {len(ausentes)} bucket(s) conocidos "
            f"(p. ej. {', '.join(ausentes[:5])}): share re-compartido incompleto o "
            "volcado del share equivocado",
        }

    return {
        "ok": True,
        "causa": None,
        "faltan_rutas": [],
        "faltan_buckets": {},
        "veredicto": f"la sesión ve la biblioteca del volcado "
        f"({', '.join(esperado['etiquetas'])}): {esperado['files']} archivos, "
        f"{esperado['titulos']} títulos",
    }


def medir(mega_bin: Path, esperado: dict, *, timeout: int = T_LISTADO) -> dict:
    """Fotografía de lo que ve la SESIÓN ACTIVA: cuenta, in-shares, raíces y nube.

    Se separa de `verificar` para poder repetirla con cada cuenta del pool en el
    failover (`elegir_del_pool`) sin duplicar la llamada a MEGAcmd.
    """
    cuenta = ex.cuenta_activa(mega_bin)
    montados = {m["ruta"] for m in ex.montajes(mega_bin) if m["tipo"].upper() == "INSHARE"}
    listados: dict[str, list[str]] = {}
    for ruta in esperado["rutas"]:
        if ruta.lower() not in {m.lower() for m in montados}:
            continue  # sin montar: ya lo reporta el veredicto
        rc, salida = ex._mega(["mega-ls", ruta], mega_bin, timeout)
        if rc == 0:
            listados[ruta] = parsear_listado_raiz(salida)

    # Nube personal de la cuenta de turno: no entra al catálogo (solo la
    # biblioteca lo hace), pero se reporta para que los totales del volcado
    # completo no parezcan una pérdida de datos.
    nube = {"entradas": 0, "nombres": []}
    if cuenta:
        rc_nube, salida_nube = ex._mega(["mega-ls", "/"], mega_bin, timeout)
        if rc_nube == 0:
            nube = nube_propia(parsear_listado_raiz(salida_nube), interno=NUBE_INTERNA)
    return {"cuenta": cuenta, "montados": montados, "listados": listados, "nube": nube}


def informe_de(
    medicion: dict,
    esperado: dict,
    volcado: Path,
    *,
    permitir_otra: bool = False,
    herramienta: str = HERRAMIENTA,
) -> dict:
    """Informe del pre-vuelo a partir de una medición (`medir`) y la biblioteca esperada."""
    veredicto = evaluar(esperado, medicion["montados"], medicion["listados"])
    informe = {
        "generado_en": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "herramienta": herramienta,
        "ok": bool(veredicto["ok"]),
        "causa": veredicto["causa"],
        "veredicto": veredicto["veredicto"],
        "forzado": bool(permitir_otra and not veredicto["ok"]),
        "cuenta": medicion["cuenta"] or None,
        "volcado": str(volcado),
        "volcado_existe": volcado.is_file(),
        "biblioteca": {
            "etiquetas": esperado["etiquetas"],
            "rutas": esperado["rutas"],
            "titulos": esperado["titulos"],
            "files": esperado["files"],
            "buckets_esperados": sum(len(v) for v in esperado["buckets"].values()),
        },
        "inshares_montados": sorted(medicion["montados"]),
        "buckets_vistos": {ruta: len(nombres) for ruta, nombres in medicion["listados"].items()},
        "nube_propia": medicion["nube"],
        "faltan_rutas": veredicto["faltan_rutas"],
        "faltan_buckets": veredicto["faltan_buckets"],
    }
    if not medicion["cuenta"]:
        # Sin sesión utilizable el veredicto sería "falta el in-share" y despistaría
        # al operador: se dice lo que pasa (y el autovolcado ya sale con rc=4).
        informe |= {
            "ok": False,
            "causa": "sin_sesion",
            "veredicto": "no hay sesión MEGAcmd activa: no se puede verificar la biblioteca",
        }
    return informe


def verificar(
    mega_bin: Path, volcado: Path, *, permitir_otra: bool = False, timeout: int = T_LISTADO
) -> dict:
    """Ejecuta el pre-vuelo contra la sesión activa y devuelve el informe (dict)."""
    texto = volcado.read_text(encoding="utf-8") if volcado.is_file() else ""
    esperado = esperado_del_volcado(texto) if texto else dict(ESPERADO_VACIO)
    medicion = medir(mega_bin, esperado, timeout=timeout)
    return informe_de(medicion, esperado, volcado, permitir_otra=permitir_otra)


def leer_pool(path: Path) -> list[tuple[str, str]]:
    """Cuentas del fichero del pool (`email<sep>password`), [] si no hay fichero.

    A diferencia de `explorar_cuentas_mega.leer_cuentas` (herramienta manual) aquí
    no abortamos: que no haya pool no puede romper el pre-vuelo del cron.
    """
    if not path.is_file():
        return []
    try:
        return ex.leer_cuentas(path)
    except SystemExit:  # fichero sin cuentas válidas: el aviso ya se imprimió
        return []


def candidatas(cuentas: Iterable[tuple[str, str]], activa: str | None) -> list[tuple[str, str]]:
    """Cuentas del pool a probar, en orden y sin repetir la que ya está activa (pura)."""
    vistas = {(activa or "").lower()}
    pendientes: list[tuple[str, str]] = []
    for email, password in cuentas:
        if email.lower() in vistas:
            continue
        vistas.add(email.lower())
        pendientes.append((email, password))
    return pendientes


def escribir_credenciales_preferidas(destino: Path, email: str, password: str) -> Path:
    """Persiste `email`/`password` como credencial preferida (chmod 600, fuera del repo).

    Mismo formato que `guardar_credenciales_mega` (`lib/mega_session.sh`), para que
    `make credenciales` y el failover sean intercambiables.
    """
    destino = destino.expanduser()
    destino.parent.mkdir(parents=True, exist_ok=True)
    previo = os.umask(0o077)  # el temporal no debe nacer legible por terceros
    try:
        atomic_write_text(destino, f"MEGA_EMAIL={email}\nMEGA_PASSWORD={password}\n")
    finally:
        os.umask(previo)
    destino.chmod(0o600)
    return destino


def _resumen(informe: dict) -> dict:
    """Traza compacta de un informe (histórico del failover, sin credenciales)."""
    return {
        "cuenta": informe.get("cuenta"),
        "ok": bool(informe.get("ok")),
        "causa": informe.get("causa"),
        "veredicto": informe.get("veredicto"),
        "faltan_rutas": informe.get("faltan_rutas") or [],
        "faltan_buckets": informe.get("faltan_buckets") or {},
    }


def elegir_del_pool(
    mega_bin: Path,
    volcado: Path,
    *,
    cuentas_path: Path | None = None,
    timeout: int = T_LISTADO,
    guardar_elegida: bool = False,
    env_destino: Path | None = None,
    iniciar: Callable[..., dict] | None = None,
    restaurar: Callable[..., None] | None = None,
    quiet: bool = False,
) -> dict:
    """Pre-vuelo + failover GUIADO POR BIBLIOTECA (ver el docstring del módulo).

    Prueba las cuentas del pool hasta encontrar una que vea la biblioteca del
    volcado y deja la sesión en ella; si ninguna la ve, restaura las credenciales
    preferidas y devuelve el informe de la primera medición (rc=8). `iniciar` y
    `restaurar` se inyectan para poder probarlo sin MEGAcmd.
    """
    iniciar = iniciar or ex.guardar_sesion
    restaurar = restaurar or ex.restaurar_preferida
    cuentas_path = Path(cuentas_path or MEGA_CUENTAS_POR_DEFECTO).expanduser()
    env_destino = Path(env_destino or MEGA_ENV_POR_DEFECTO).expanduser()

    texto = volcado.read_text(encoding="utf-8") if volcado.is_file() else ""
    esperado = esperado_del_volcado(texto) if texto else dict(ESPERADO_VACIO)
    inicial = informe_de(
        medir(mega_bin, esperado, timeout=timeout),
        esperado,
        volcado,
        herramienta=HERRAMIENTA_POOL,
    )

    pool = leer_pool(cuentas_path)
    meta: dict = {
        "modo": "elegir_cuenta",
        "cuenta_anterior": inicial.get("cuenta"),
        "elegida": None,
        "origen": None,
        "candidatas": [],
        "inicial": _resumen(inicial),
        "pool": {"fichero": str(cuentas_path), "cuentas": [email for email, _ in pool]},
        "restaurado": False,
    }

    if inicial["ok"]:
        # La sesión ya ve la biblioteca: no se toca (ni se leen credenciales).
        return inicial | meta | {"elegida": inicial.get("cuenta"), "origen": "sesion_activa"}

    elegido: dict | None = None
    elegido_email = elegido_password = ""
    for email, password in candidatas(pool, inicial.get("cuenta")):
        login = iniciar(mega_bin, email, password)
        informe = informe_de(
            medir(mega_bin, esperado, timeout=timeout),
            esperado,
            volcado,
            herramienta=HERRAMIENTA_POOL,
        )
        meta["candidatas"].append(
            {"email": email, "login": login.get("estado"), **_resumen(informe)}
        )
        if informe["ok"]:
            elegido, elegido_email, elegido_password = informe, email, password
            break

    if elegido is None:
        # Nadie del pool ve la biblioteca: se deja el host con la credencial
        # preferida (como estaba) y el informe de la primera medición explica por qué.
        restaurar(mega_bin, quiet=quiet)
        return inicial | meta | {"restaurado": bool(inicial.get("cuenta"))}

    meta |= {"elegida": elegido_email, "origen": "pool"}
    if guardar_elegida:
        meta["credenciales_guardadas"] = str(
            escribir_credenciales_preferidas(env_destino, elegido_email, elegido_password)
        )
    return elegido | meta


def codigo_salida(informe: dict) -> int:
    """rc del pre-vuelo: 4 sin sesión · 8 biblioteca distinta · 0 ok (o forzado)."""
    if informe.get("causa") == "sin_sesion":
        return EXIT_SIN_SESION
    if informe.get("ok") or informe.get("forzado"):
        return EXIT_OK
    return EXIT_BIBLIOTECA_DISTINTA


def _imprimir_failover(informe: dict) -> None:
    """Traza de `--elegir-cuenta`: de qué cuenta se sale y por cuáles se pasó."""
    anterior = informe.get("cuenta_anterior") or "<ninguna>"
    if informe.get("origen") == "sesion_activa":
        print(
            f"   · failover: la sesión {anterior} ya ve la biblioteca; no se prueba el pool",
            flush=True,
        )
        return
    pool = informe.get("pool") or {}
    print(
        f"   · failover: {anterior} NO ve la biblioteca; probando "
        f"{len(pool.get('cuentas') or [])} cuenta(s) de {pool.get('fichero') or '<sin pool>'}",
        flush=True,
    )
    for candidata in informe.get("candidatas") or []:
        marca = "✔" if candidata.get("ok") else "✖"
        print(
            f"   · {marca} {candidata.get('email')} (login={candidata.get('login')}): "
            f"{candidata.get('veredicto')}",
            flush=True,
        )
    if informe.get("elegida"):
        cola = (
            f" · credenciales guardadas en {informe['credenciales_guardadas']}"
            if informe.get("credenciales_guardadas")
            else ""
        )
        print(
            f"   · cuenta elegida: {informe['elegida']} (origen={informe.get('origen')}){cola}",
            flush=True,
        )
    else:
        print(
            "   · ninguna cuenta del pool ve la biblioteca: se restaura la credencial preferida",
            flush=True,
        )


def _imprimir(informe: dict, estado_path: Path | None, quiet: bool) -> None:
    if quiet:
        return
    # Todo con `.get`: este fichero también se imprime a partir de informes ya
    # escritos por versiones anteriores (y de informes a medias del failover).
    icono = "✔" if informe.get("ok") else "✖"
    print(f"{icono} {informe.get('veredicto') or '(sin veredicto)'}", flush=True)
    biblioteca = informe.get("biblioteca") or {}
    print(f"   · cuenta: {informe.get('cuenta') or '<ninguna>'}", flush=True)
    if biblioteca.get("etiquetas"):
        print(
            f"   · biblioteca del volcado: {', '.join(biblioteca['etiquetas'])} "
            f"({biblioteca.get('files', 0)} archivos, {biblioteca.get('titulos', 0)} títulos, "
            f"{biblioteca.get('buckets_esperados', 0)} buckets)",
            flush=True,
        )
    print(
        f"   · in-shares montados: {len(informe.get('inshares_montados') or [])}; "
        f"raíces listadas: {informe.get('buckets_vistos') or '{}'}",
        flush=True,
    )
    if informe.get("faltan_rutas"):
        print(f"   · faltan in-shares: {', '.join(informe['faltan_rutas'])}", flush=True)
    nube = informe.get("nube_propia") or {}
    if nube.get("entradas"):
        muestra = ", ".join(nube.get("nombres") or [])
        print(
            f"   · nube propia de la cuenta: {nube['entradas']} entrada(s) fuera de la "
            f"biblioteca ({muestra}) → no se indexan",
            flush=True,
        )
    for ruta, ausentes in (informe.get("faltan_buckets") or {}).items():
        print(f"   · {ruta}: faltan buckets {', '.join(ausentes[:10])}", flush=True)
    if informe.get("modo") == "elegir_cuenta":
        _imprimir_failover(informe)
    if informe.get("forzado"):
        print("   · AVISO: se continúa por --permitir-otra-biblioteca", flush=True)
    if estado_path is not None:
        print(f"   · estado: {estado_path}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Pre-vuelo de rotación: ¿la cuenta MEGA de la semana ve la "
        "biblioteca del volcado vigente? (no toca el volcado)"
    )
    ap.add_argument(
        "--volcado",
        default=os.environ.get("ALUCARD_VOLCADO", str(VOLCADO_POR_DEFECTO)),
        help="volcado canónico que define la biblioteca esperada",
    )
    ap.add_argument("--mega-bin", default=os.environ.get("MEGA_BIN", rv.MEGA_BIN_DEFAULT))
    ap.add_argument(
        "--json", default=str(ESTADO_POR_DEFECTO), help="estado para la API ('' = no escribir)"
    )
    ap.add_argument("--timeout", type=int, default=T_LISTADO, help="timeout del mega-ls (s)")
    ap.add_argument(
        "--permitir-otra-biblioteca",
        action="store_true",
        help="no falla aunque la sesión vea otro share (vaciado consciente)",
    )
    ap.add_argument(
        "--elegir-cuenta",
        action="store_true",
        help="failover: si la sesión no ve la biblioteca, prueba el pool y se queda "
        "con la primera cuenta que sí la ve (deja esa sesión activa)",
    )
    ap.add_argument(
        "--cuentas",
        default=str(MEGA_CUENTAS_POR_DEFECTO),
        help="pool de cuentas (`email<sep>password`, chmod 600) para --elegir-cuenta",
    )
    ap.add_argument(
        "--guardar-elegida",
        action="store_true",
        help="con --elegir-cuenta: persiste la cuenta elegida como credencial "
        "preferida (chmod 600, fuera del repo)",
    )
    ap.add_argument(
        "--env-destino",
        default=str(MEGA_ENV_POR_DEFECTO),
        help="fichero de credenciales preferidas que escribe --guardar-elegida",
    )
    ap.add_argument("--quiet", action="store_true", help="solo estado por código de salida")
    args = ap.parse_args()

    mega_bin = Path(args.mega_bin).expanduser()
    if not (mega_bin / "mega-cmd").is_file():
        print(f"MEGAcmd no disponible en {mega_bin} (usa --mega-bin o MEGA_BIN)", file=sys.stderr)
        return EXIT_SIN_SESION

    if args.elegir_cuenta and args.permitir_otra_biblioteca:
        print(
            "AVISO: --permitir-otra-biblioteca no aplica con --elegir-cuenta "
            "(ese modo solo acepta la biblioteca del volcado)",
            file=sys.stderr,
        )

    volcado = Path(args.volcado).expanduser().resolve()
    if args.elegir_cuenta:
        informe = elegir_del_pool(
            mega_bin,
            volcado,
            cuentas_path=Path(args.cuentas),
            timeout=args.timeout,
            guardar_elegida=args.guardar_elegida,
            env_destino=Path(args.env_destino),
            quiet=args.quiet,
        )
    else:
        informe = verificar(
            mega_bin, volcado, permitir_otra=args.permitir_otra_biblioteca, timeout=args.timeout
        )
    estado_path = Path(args.json).expanduser().resolve() if args.json else None
    if estado_path is not None:
        estado_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(estado_path, json.dumps(informe, ensure_ascii=False, indent=1) + "\n")
    _imprimir(informe, estado_path, args.quiet)
    return codigo_salida(informe)


if __name__ == "__main__":
    raise SystemExit(main())
