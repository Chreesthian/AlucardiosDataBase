"""Exploración multi-cuenta de MEGA: identidad de biblioteca y nombres de share.

Dos contratos que el pipeline no puede romper:

1. El nombre del *in-share* puede llevar espacios (`INSHARE on
   //from/dueño@gmail.com:ORTIK 90 (read access)`). Cortarlo en el primer espacio
   produce una ruta inexistente ("Couldn't find") y dejaría el volcado sin datos.
2. Cuentas que montan bibliotecas DISTINTAS no se mezclan entre sí: los títulos
   de un share retro no deben contarse como títulos Switch "que faltan".
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:  # la exploración vive en scripts/
    sys.path.insert(0, str(REPO / "scripts"))

import explorar_cuentas_mega as explorar  # noqa: E402
import refrescar_volcado as refresco  # noqa: E402

from app.ingest import bucket_letter  # noqa: E402

SHARE_SWITCH = "INSHARE biblioteca.demo@gmail.com:BCKP2"
SHARE_RETRO = "INSHARE biblioteca.demo@gmail.com:ORTIK 90"

MONTAJES = (
    "ROOT on /\n"
    "INBOX on //in\n"
    "RUBBISH on //bin\n"
    "INSHARE on //from/biblioteca.demo@gmail.com:ORTIK 90 (read access)\n"
)

CABECERA = (
    "VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)\n"
    "=======================================================================\n"
    "Cuenta            : semana@example.com\n"
    "Fecha de volcado  : 2026-09-30T06:00:00+00:00\n"
    "Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)\n"
)
SECTOR_SWITCH = (
    "SECTOR: " + SHARE_SWITCH + "\n"
    "Archivos  : 2\n"
    "Carpetas  : 6\n"
    "Tamano    : 31457280 bytes (30.00 MiB)\n"
    "\n"
    "[ROOT] //from/biblioteca.demo@gmail.com:BCKP2/\n"
    "|-- [FOLDER] -- A/\n"
    "|   `-- [FOLDER] Juego Uno/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] uno.nsp  (10485760 bytes)\n"
    "`-- [FOLDER] -- B/\n"
    "    `-- [FOLDER] Juego Dos/\n"
    "        `-- [FOLDER] B-ASE/\n"
    "            `-- [FILE] dos.nsp  (20971520 bytes)\n"
)
SECTOR_RETRO = (
    "SECTOR: " + SHARE_RETRO + "\n"
    "Archivos  : 1\n"
    "Carpetas  : 3\n"
    "Tamano    : 5242880 bytes (5.00 MiB)\n"
    "\n"
    "[ROOT] //from/biblioteca.demo@gmail.com:ORTIK 90/\n"
    "`-- [FOLDER] -- ARC Mame2003/\n"
    "    `-- [FOLDER] Penguin Brothers/\n"
    "        `-- [FOLDER] B-ASE/\n"
    "            `-- [FILE] penguin.zip  (5242880 bytes)\n"
)


def _cuenta(email: str, share: str, titulos: dict[str, int]) -> dict:
    """Cuenta sintética con los campos que consume `comparar`."""
    info: dict[str, dict] = {}
    for clave, tam in titulos.items():
        bucket, nombre = clave.split("/", 1)
        info[clave] = {
            "clave": clave,
            "titulo": nombre,
            "bucket": bucket,
            "letra": bucket_letter(bucket),
            "bytes": tam,
            "tipos": {"base": 1},
            "_sectores": {share},
            "_versiones": {"B-ASE"},
            "_archivos": {f"{nombre}.nsp": tam},
        }
    return {
        "email": email,
        "ok": True,
        "sesion": {"estado": "ok", "detalle": "sesión propia", "cuenta": email},
        "montajes": [
            {
                "tipo": "INSHARE",
                "ruta": share.replace("INSHARE ", "//from/"),
                "acceso": "read access",
            }
        ],
        "totales": {
            "files": len(info) or 1,
            "folders": len(info),
            "bytes": sum(titulos.values()),
        },
        "titulos_n": len(info),
        "_titulos": info,
        "sectores": [
            {
                "sector": share,
                "files": len(info) or 1,
                "folders": len(info),
                "bytes": sum(titulos.values()),
                "buckets": sorted({c.split("/", 1)[0] for c in titulos}),
                "titulos": len(info),
            }
        ],
    }


def test_montajes_conservan_espacios_del_share():
    """Regresión: `\\S+` cortaba "ORTIK 90" en "ORTIK" y la ruta no existía."""
    montajes = explorar._parsear_montajes(MONTAJES)

    assert [m["tipo"] for m in montajes] == ["ROOT", "INBOX", "RUBBISH", "INSHARE"]
    assert montajes[-1]["ruta"] == "//from/biblioteca.demo@gmail.com:ORTIK 90"
    assert montajes[-1]["acceso"] == "read access"


def test_etiqueta_de_sector_conserva_el_share_completo():
    etiqueta = refresco.etiqueta_sector("//from/biblioteca.demo@gmail.com:ORTIK 90")

    assert etiqueta == "INSHARE biblioteca.demo@gmail.com:ORTIK 90"


def test_raices_inshare_del_guardian_canonico_conservan_espacios():
    """El guardián del volcado usa el MISMO criterio: la ruta entera, con espacios."""
    assert refresco._RE_INSHARE.findall(
        "INSHARE on //from/biblioteca.demo@gmail.com:ORTIK 90 (read access)\n"
    ) == ["//from/biblioteca.demo@gmail.com:ORTIK 90"]
    assert refresco._RE_INSHARE.findall("INSHARE on //from/biblioteca.demo@gmail.com:BCKP2\n") == [
        "//from/biblioteca.demo@gmail.com:BCKP2"
    ]


def test_leer_cuentas_ignora_comentarios_y_duplicados(tmp_path):
    """Formato: `email<TAB>contraseña`; sin líneas en blanco, comentarios ni repetidas."""
    fichero = tmp_path / "mega_cuentas.txt"
    fichero.write_text(
        "# rotación semanal\n"
        "\n"
        "dts.02.swch@gmail.com\tclave-dos\n"
        "dts.03.swch@gmail.com\tclave-tres\n"
        "dts.02.swch@gmail.com\tclave-duplicada\n"
        "sinSeparador\n",
        encoding="utf-8",
    )
    fichero.chmod(0o600)

    assert explorar.leer_cuentas(fichero) == [
        ("dts.02.swch@gmail.com", "clave-dos"),
        ("dts.03.swch@gmail.com", "clave-tres"),
    ]


def _vigente() -> str:
    return CABECERA + SECTOR_SWITCH


def test_una_biblioteca_distinta_no_se_mezcla_con_la_canonica():
    """Regresión: los títulos de un share retro no son "títulos Switch que faltan"."""
    switch = {"-- A/Juego Uno": 10485760, "-- B/Juego Dos": 20971520}
    retro = {"-- T/Tetris (Atari)": 5242880}
    cuentas = [
        _cuenta("dts.02.swch@gmail.com", SHARE_SWITCH, switch),
        _cuenta("dts.03.swch@gmail.com", SHARE_SWITCH, switch),
        _cuenta("dts.01.others@gmail.com", SHARE_RETRO, retro),
    ]

    comp = explorar.comparar(cuentas, _vigente())

    assert comp["biblioteca_canonica"] == SHARE_SWITCH
    assert [g["es_canonica"] for g in comp["bibliotecas"]] == [True, False]  # canónica primero

    canonica, otra = comp["bibliotecas"]
    assert canonica["etiqueta"] == SHARE_SWITCH
    assert canonica["cuentas"] == ["dts.02.swch@gmail.com", "dts.03.swch@gmail.com"]
    assert canonica["titulos_union"] == 2  # el título retro NO entra aquí
    assert canonica["titulos_en_todas"] == 2
    assert canonica["intercambiables"]  # ambas ven exactamente el mismo catálogo
    assert [c["titulos_que_faltan"] for c in canonica["cobertura"]] == [0, 0]
    assert canonica["parciales_total"] == 0

    vs = canonica["vs_volcado_vigente"]
    assert vs["titulos_en_vigente"] == 2
    assert vs["titulos_que_aportarian_las_cuentas"] == 0
    assert vs["titulos_del_vigente_que_ninguna_cuenta_alcanza"] == 0

    assert otra["etiqueta"] == SHARE_RETRO
    assert otra["cuentas"] == ["dts.01.others@gmail.com"]
    assert otra["titulos_union"] == 1  # su catálogo se mide aparte
    assert otra["intercambiables"] is False  # una sola cuenta en esa biblioteca
    # No se compara contra el volcado canónico: son bibliotecas distintas.
    assert otra["vs_volcado_vigente"] is None


def test_informe_y_recomendacion_cubren_ambas_bibliotecas():
    """El informe separa bibliotecas y la recomendación no propone mezclarlas."""
    switch = {"-- A/Juego Uno": 10485760, "-- B/Juego Dos": 20971520}
    cuentas = [
        _cuenta("dts.02.swch@gmail.com", SHARE_SWITCH, switch),
        _cuenta("dts.03.swch@gmail.com", SHARE_SWITCH, switch),
        _cuenta("dts.01.others@gmail.com", SHARE_RETRO, {"-- T/Tetris (Atari)": 5242880}),
    ]
    comp = explorar.comparar(cuentas, _vigente())
    informe = {
        "generado_en": "2026-09-30T06:00:00+00:00",
        "herramienta": "explorar_cuentas_mega.py",
        "fichero_cuentas": "~/.config/alucard/mega_cuentas.txt",
        "volcado_vigente": {"ruta": "dump.txt", "fuente": SHARE_SWITCH, "titulos": 2},
        "cuentas": [explorar.vista(c) for c in cuentas],
        "comparacion": comp,
    }
    informe["recomendacion"] = explorar.recomendacion(cuentas, comp)
    texto = explorar.informe_markdown(informe)

    assert SHARE_SWITCH.replace("INSHARE ", "`INSHARE ") in texto
    assert SHARE_RETRO in texto
    assert "dts.01.others@gmail.com" in texto  # la cuenta retro queda documentada
    renglones = " ".join(informe["recomendacion"])
    assert "dts.01" in renglones  # se avisa de la cuenta que NO sirve para el volcado
    assert "dts.02" in renglones and "dts.03" in renglones  # rotación segura
    # Ningún informe debe filtrar credenciales: solo se guardan emails.
    assert "clave" not in "\n".join(informe["recomendacion"])


# ── Asentamiento de la sesión MEGAcmd ────────────────────────────────────────
# `mega-login` devuelve rc=0 ANTES de montar la sesión (su rc no es fiable) y
# `mega-logout --keep-session` antes de cerrarla: sin esperar, un login CORRECTO
# se lee como fallido y el pipeline repite logins (cada uno es un riesgo: las
# credenciales rotan y la sesión de MEGAcmd es única). Medido en el host real:
# ~2-7 s por login. Estas pruebas fijan ese contrato con MEGAcmd simulado.


def _mega_simulado(estado: dict, *, asentar_tras: int = 3):
    """MEGAcmd simulado: la cuenta del login tarda `asentar_tras` whoamis en verse."""
    llamadas: list[tuple[str, ...]] = []

    def _mega(args, _bin, _timeout):
        llamadas.append(tuple(args))
        if args[0] == "mega-session":
            return 0, "Your (secret) session is: CLAVE\n"
        if args[0] == "mega-logout":
            estado["cuenta"] = ""
            estado["pendiente"] = ""
            return 0, ""
        if args[0] == "mega-login":
            estado["pendiente"] = args[1]
            estado["whoamis"] = 0
            return 0, ""  # rc=0 aunque la sesión aún no esté lista (caso real)
        if args[0] == "mega-whoami":
            if estado["pendiente"]:
                estado["whoamis"] += 1
                if estado["whoamis"] >= asentar_tras:
                    estado["cuenta"], estado["pendiente"] = estado["pendiente"], ""
            return 0, f"Account e-mail: {estado['cuenta']}\n"
        return 1, ""

    return _mega, llamadas


def _logins(llamadas: list[tuple[str, ...]], email: str = "") -> int:
    """Cuántos `mega-login` se hicieron (a `email`, si se indica)."""
    return sum(1 for c in llamadas if c[0] == "mega-login" and (not email or c[1] == email))


def _estado_simulado(cuenta: str = "previa@example.com") -> dict:
    return {"cuenta": cuenta, "pendiente": "", "whoamis": 0}


def test_un_login_correcto_no_se_repite_por_una_carrera_de_megacmd(monkeypatch, tmp_path):
    """El login asienta tarde: se espera y NO se repite el login."""
    estado = _estado_simulado()
    _mega, llamadas = _mega_simulado(estado)
    monkeypatch.setattr(explorar, "_mega", _mega)
    monkeypatch.setattr(explorar, "ESPERA_SONDA", 0)

    res = explorar.guardar_sesion(tmp_path / "bin", "nueva@example.com", "clave")

    assert res["estado"] == "login"
    assert estado["cuenta"] == "nueva@example.com"
    assert _logins(llamadas, "nueva@example.com") == 1  # la espera evitó el 2º intento
    assert "rotación desde previa@example.com" in res["detalle"]


def test_si_la_sesion_ya_es_la_cuenta_no_se_reloguea(monkeypatch, tmp_path):
    """Reutilizar la sesión vigente es lo más barato y lo más seguro."""
    estado = _estado_simulado("nueva@example.com")
    _mega, llamadas = _mega_simulado(estado)
    monkeypatch.setattr(explorar, "_mega", _mega)

    res = explorar.guardar_sesion(tmp_path / "bin", "nueva@example.com", "clave")

    assert res["estado"] == "reutilizada"
    assert _logins(llamadas) == 0
    assert not [c for c in llamadas if c[0] == "mega-logout"]


def test_un_login_que_no_asienta_se_intenta_dos_veces_y_no_cuelga(monkeypatch, tmp_path):
    """`rc=0` con una sesión que nunca llega: dos intentos, error claro y sin esperas."""
    estado = _estado_simulado()
    _mega, llamadas = _mega_simulado(estado, asentar_tras=10**9)
    monkeypatch.setattr(explorar, "_mega", _mega)
    monkeypatch.setattr(explorar, "ESPERA_SONDA", 0)
    monkeypatch.setattr(explorar, "T_ESPERA_LOGIN", 0)
    monkeypatch.setattr(explorar, "T_ESPERA_LOGOUT", 0)

    res = explorar.guardar_sesion(tmp_path / "bin", "nueva@example.com", "clave")

    assert res["estado"] == "error"
    # Dos intentos con la cuenta nueva (no se rinde a la primera por una carrera)…
    assert _logins(llamadas, "nueva@example.com") == explorar.INTENTOS_LOGIN
    # …y la sesión previa se retoma con su clave para no dejar el host sin sesión.
    assert _logins(llamadas, "CLAVE") == 1
    assert "login fallido" in res["detalle"]


def test_esperar_cuenta_distingue_sesion_objetivo_cierre_y_cualquiera(monkeypatch, tmp_path):
    """La espera acotada cubre los tres estados que necesita el pipeline."""
    estado = _estado_simulado("activa@example.com")
    _mega, _ = _mega_simulado(estado)
    monkeypatch.setattr(explorar, "_mega", _mega)
    monkeypatch.setattr(explorar, "ESPERA_SONDA", 0)
    monkeypatch.setattr(explorar, "T_ESPERA_LOGIN", 0)
    b = tmp_path / "bin"

    assert explorar._esperar_cuenta(b, "activa@example.com") == "activa@example.com"
    assert explorar._esperar_cuenta(b) == "activa@example.com"  # cualquiera
    # email="" espera al CIERRE: con sesión abierta devuelve (acotado) la cuenta.
    assert explorar._esperar_cuenta(b, "") == "activa@example.com"
    estado["cuenta"] = ""
    assert explorar._esperar_cuenta(b, "") == ""  # cerrada: asienta al instante
    assert explorar._esperar_cuenta(b) == ""  # sin sesión y sin margen: no miente
