"""Failover de rotación guiado por BIBLIOTECA (`verificar_rotacion.py --elegir-cuenta`).

Contrato: entrar en MEGA y VER la biblioteca son dos cosas distintas. El pool
(`lib/mega_session.sh`) responde a la primera; el pre-vuelo, a la segunda. Si la
credencial de la semana entra pero monta OTRO share, el cron no puede quedarse en
rc=8 cada 6 h habiendo en el pool una cuenta que sí ve la biblioteca: se prueba el
pool (segundos por cuenta) y la sesión se queda en la primera que la ve. Si
ninguna la ve, se restaura la credencial preferida y el rc sigue siendo 8.

Dos invariantes que no se pueden romper: el volcado no se toca (este modo no
escribe nada) y ninguna contraseña del pool acaba en el informe, que es lo que la
API publica en `GET /api/sync/cuentas`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:  # el pre-vuelo vive en scripts/
    sys.path.insert(0, str(REPO / "scripts"))

import verificar_rotacion as pre  # noqa: E402

PREFERIDA = "semana@example.com"
BUENA = "dts.02.swch@gmail.com"
RETRO = "dts.01.others@gmail.com"
TERCERA = "dts.03.swch@gmail.com"

SHARE = "INSHARE biblioteca.demo@gmail.com:BCKP1"
RUTA = "//from/biblioteca.demo@gmail.com:BCKP1"
RUTA_RETRO = "//from/biblioteca.demo@gmail.com:ORTIK 90"
BUCKETS = ["-- A", "-- B"]

CABECERA = (
    "VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)\n"
    "=======================================================================\n"
    f"Cuenta            : {PREFERIDA}\n"
    "Fecha de volcado  : 2026-09-30T06:00:00+00:00\n"
    "Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)\n"
)
SECTOR_SHARE = (
    "SECTOR: " + SHARE + "\n"
    "Archivos  : 2\n"
    "Carpetas  : 6\n"
    "Tamano    : 31457280 bytes (30.00 MiB)\n"
    "\n"
    f"[ROOT] {RUTA}/\n"
    "|-- [FOLDER] -- A/\n"
    "|   `-- [FOLDER] Juego Uno/\n"
    "|       `-- [FOLDER] B-ASE/\n"
    "|           `-- [FILE] uno.nsp  (10485760 bytes)\n"
    "`-- [FOLDER] -- B/\n"
    "    `-- [FOLDER] Juego Dos/\n"
    "        `-- [FOLDER] B-ASE/\n"
    "            `-- [FILE] dos.nsp  (20971520 bytes)\n"
)
# Campos del informe que consume la API (`GET /api/sync/cuentas`): el modo de
# failover no puede dejar de publicarlos.
CLAVES_API = (
    "generado_en",
    "herramienta",
    "ok",
    "causa",
    "veredicto",
    "forzado",
    "cuenta",
    "volcado",
    "volcado_existe",
    "biblioteca",
    "inshares_montados",
    "buckets_vistos",
    "nube_propia",
    "faltan_rutas",
    "faltan_buckets",
)


def _volcado(tmp_path: Path) -> Path:
    ruta = tmp_path / "volcado.txt"
    ruta.write_text(CABECERA + SECTOR_SHARE, encoding="utf-8")
    return ruta


def _pool(tmp_path: Path, cuentas: list[tuple[str, str]]) -> Path:
    """Fichero de cuentas del pool con el formato real (`email<sep>password`)."""
    ruta = tmp_path / "mega_cuentas.txt"
    ruta.write_text("".join(f"{email}\t{clave}\n" for email, clave in cuentas), encoding="utf-8")
    ruta.chmod(0o600)
    return ruta


def _bin(tmp_path: Path) -> Path:
    return tmp_path / "mega-bin"


def _sesion(
    monkeypatch: pytest.MonkeyPatch,
    inicial: str,
    rutas: dict[str, dict[str, list[str]]],
) -> dict:
    """MEGAcmd simulado: `rutas[cuenta][ruta]` son los buckets que esa cuenta ve.

    Se parchean las primitivas de MEGAcmd (no `medir`), así el test cubre de
    verdad la medición, el veredicto y el informe.
    """
    estado = {"cuenta": inicial}

    def _mega(args: list[str], _bin: Path, _timeout: int) -> tuple[int, str]:
        if args[0] != "mega-ls":
            return 1, ""
        ruta = args[1] if len(args) > 1 else "/"
        if ruta == "/":
            return 0, "S4 Object storage\n"  # nube personal de la cuenta
        nombres = rutas.get(estado["cuenta"], {}).get(ruta)
        if nombres is None:
            return 9, f"Couldn't find {ruta}"
        return 0, f"{ruta}/: \n" + "\n".join(nombres) + "\n"

    monkeypatch.setattr(pre.ex, "cuenta_activa", lambda _b: estado["cuenta"])
    monkeypatch.setattr(
        pre.ex,
        "montajes",
        lambda _b: [
            {"tipo": "INSHARE", "ruta": ruta, "acceso": "read access"}
            for ruta in rutas.get(estado["cuenta"], {})
        ],
    )
    monkeypatch.setattr(pre.ex, "_mega", _mega)
    return estado


def _login(estado: dict, *, fallan: set[str] = frozenset()):
    """`iniciar` simulado: la cuenta queda activa (y sus montajes con ella)."""

    def iniciar(_bin: Path, email: str, _password: str) -> dict:
        if email in fallan:
            return {"estado": "error", "detalle": "login fallido"}
        estado["cuenta"] = email
        return {"estado": "login", "detalle": "rotación"}

    return iniciar


def _restaurador(estado: dict, llamadas: list):
    def restaurar(_bin: Path, *, quiet: bool = False) -> None:
        llamadas.append(quiet)
        estado["cuenta"] = PREFERIDA

    return restaurar


def test_si_la_sesion_ya_ve_la_biblioteca_no_se_prueba_el_pool(tmp_path, monkeypatch):
    """El camino normal no gasta logins ni toca la sesión de nadie."""
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA: BUCKETS}})
    pool = _pool(tmp_path, [(RETRO, "clave-retro")])
    llamadas: list = []

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        _volcado(tmp_path),
        cuentas_path=pool,
        iniciar=_login(estado),
        restaurar=_restaurador(estado, llamadas),
    )

    assert informe["ok"] is True
    assert informe["origen"] == "sesion_activa"
    assert informe["elegida"] == PREFERIDA
    assert informe["candidatas"] == []
    assert llamadas == []
    assert estado["cuenta"] == PREFERIDA


def test_elige_la_primera_cuenta_del_pool_que_ve_la_biblioteca(tmp_path, monkeypatch):
    """Entrar no basta: la cuenta retro entra y aun así no se elige."""
    rutas = {RETRO: {RUTA_RETRO: ["-- X"]}, BUENA: {RUTA: BUCKETS}, TERCERA: {RUTA: BUCKETS}}
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA_RETRO: ["-- X"]}, **rutas})
    pool = _pool(tmp_path, [(RETRO, "clave-retro"), (BUENA, "clave-buena"), (TERCERA, "clave-3")])
    llamadas: list = []

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        _volcado(tmp_path),
        cuentas_path=pool,
        iniciar=_login(estado),
        restaurar=_restaurador(estado, llamadas),
    )

    assert informe["ok"] is True and informe["causa"] is None
    assert pre.codigo_salida(informe) == pre.EXIT_OK
    assert informe["elegida"] == BUENA and informe["origen"] == "pool"
    assert informe["cuenta_anterior"] == PREFERIDA
    assert informe["inicial"]["ok"] is False  # la preferida no la veía
    assert informe["inicial"]["faltan_rutas"] == [RUTA]
    assert [c["email"] for c in informe["candidatas"]] == [RETRO, BUENA]
    assert [c["ok"] for c in informe["candidatas"]] == [False, True]
    assert [c["login"] for c in informe["candidatas"]] == ["login", "login"]
    assert estado["cuenta"] == BUENA  # la sesión queda en la que ve la biblioteca
    assert llamadas == []  # no hay nada que restaurar
    assert informe["biblioteca"]["etiquetas"] == [SHARE]
    assert informe["inshares_montados"] == [RUTA]  # el informe es el de la elegida


def test_un_login_fallido_del_pool_no_bloquea_al_siguiente(tmp_path, monkeypatch):
    """Contraseña caducada en el pool: se salta la cuenta y se sigue probando."""
    rutas = {BUENA: {RUTA: BUCKETS}}
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA_RETRO: ["-- X"]}, **rutas})
    pool = _pool(tmp_path, [("caducada@example.com", "clave-vieja"), (BUENA, "clave-buena")])

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        _volcado(tmp_path),
        cuentas_path=pool,
        iniciar=_login(estado, fallan={"caducada@example.com"}),
        restaurar=_restaurador(estado, []),
    )

    assert [c["login"] for c in informe["candidatas"]] == ["error", "login"]
    assert informe["elegida"] == BUENA


def test_sin_cuenta_en_el_pool_se_restaura_la_preferida_y_rc_8(tmp_path, monkeypatch):
    """Nadie ve la biblioteca: se deja el host como estaba y se falla ruidoso."""
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA_RETRO: ["-- X"]}})
    pool = _pool(tmp_path, [(RETRO, "clave-retro"), (BUENA, "clave-buena")])
    llamadas: list = []

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        _volcado(tmp_path),
        cuentas_path=pool,
        iniciar=_login(estado),
        restaurar=_restaurador(estado, llamadas),
        quiet=True,
    )

    assert informe["ok"] is False
    assert informe["causa"] == "inshare_ausente"
    assert informe["faltan_rutas"] == [RUTA]
    assert pre.codigo_salida(informe) == pre.EXIT_BIBLIOTECA_DISTINTA
    assert informe["elegida"] is None and informe["origen"] is None
    assert informe["restaurado"] is True
    assert estado["cuenta"] == PREFERIDA  # se retoma la credencial preferida
    assert llamadas == [True]  # `quiet` se propaga a la restauración
    # El informe que se publica es el de la cuenta preferida, no el de la última
    # candidata: es el que el operador necesita para entender el fallo.
    assert informe["cuenta"] == PREFERIDA
    assert [c["email"] for c in informe["candidatas"]] == [RETRO, BUENA]


def test_sin_pool_no_se_inventan_cuentas(tmp_path, monkeypatch):
    """Sin fichero de pool el modo sigue siendo inofensivo (y no toca el volcado)."""
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA_RETRO: ["-- X"]}})
    volcado = _volcado(tmp_path)
    antes = volcado.read_text(encoding="utf-8")

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        volcado,
        cuentas_path=tmp_path / "no-existe.txt",
        iniciar=_login(estado),
        restaurar=_restaurador(estado, []),
    )

    assert informe["pool"]["cuentas"] == []
    assert informe["candidatas"] == []
    assert pre.codigo_salida(informe) == pre.EXIT_BIBLIOTECA_DISTINTA
    assert volcado.read_text(encoding="utf-8") == antes  # ni se roza el volcado


def test_guardar_elegida_persiste_la_credencial_con_chmod_600(tmp_path, monkeypatch):
    """`--guardar-elegida` evita repetir la búsqueda en el siguiente ciclo del cron."""
    rutas = {BUENA: {RUTA: BUCKETS}}
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA_RETRO: ["-- X"]}, **rutas})
    pool = _pool(tmp_path, [(BUENA, "clave-buena")])
    destino = tmp_path / "config" / "mega.env"

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        _volcado(tmp_path),
        cuentas_path=pool,
        iniciar=_login(estado),
        restaurar=_restaurador(estado, []),
        guardar_elegida=True,
        env_destino=destino,
    )

    assert informe["credenciales_guardadas"] == str(destino)
    assert destino.read_text(encoding="utf-8") == f"MEGA_EMAIL={BUENA}\nMEGA_PASSWORD=clave-buena\n"
    assert destino.stat().st_mode & 0o777 == 0o600


def test_el_informe_nunca_lleva_las_contrasenas_del_pool(tmp_path, monkeypatch, capsys):
    """El informe lo publica la API y el log lo lee cron: cero credenciales."""
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA_RETRO: ["-- X"]}})
    pool = _pool(tmp_path, [(RETRO, "clave-secreta-retro"), (BUENA, "clave-secreta-buena")])

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        _volcado(tmp_path),
        cuentas_path=pool,
        iniciar=_login(estado),
        restaurar=_restaurador(estado, []),
    )
    pre._imprimir(informe, None, quiet=False)
    salida = capsys.readouterr().out
    serializado = json.dumps(informe, ensure_ascii=False)

    assert "clave-secreta" not in serializado and "clave-secreta" not in salida
    assert BUENA in salida and RETRO in salida  # los emails sí interesan
    assert "cuenta elegida" not in salida  # ninguna la ve: lo dice el mensaje de fallo
    assert "ninguna cuenta del pool ve la biblioteca" in salida


def test_el_modo_de_failover_mantiene_el_contrato_de_la_api(tmp_path, monkeypatch):
    """`GET /api/sync/cuentas` no puede perder campos por usar este modo."""
    rutas = {BUENA: {RUTA: BUCKETS}}
    estado = _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA_RETRO: ["-- X"]}, **rutas})
    pool = _pool(tmp_path, [(BUENA, "clave-buena")])

    informe = pre.elegir_del_pool(
        _bin(tmp_path),
        _volcado(tmp_path),
        cuentas_path=pool,
        iniciar=_login(estado),
        restaurar=_restaurador(estado, []),
    )

    assert set(CLAVES_API) <= set(informe)


def test_verificar_mantiene_el_informe_clasico(tmp_path, monkeypatch):
    """El refactor `medir`/`informe_de` no cambia lo que ya consumía la API."""
    _sesion(monkeypatch, PREFERIDA, {PREFERIDA: {RUTA: BUCKETS}})

    informe = pre.verificar(_bin(tmp_path), _volcado(tmp_path))

    assert set(CLAVES_API) == set(informe)  # sin campos extra en el modo clásico
    assert informe["herramienta"] == pre.HERRAMIENTA
    assert informe["ok"] is True and informe["veredicto"].startswith("la sesión ve la biblioteca")
    assert informe["cuenta"] == PREFERIDA


def test_candidatas_deduce_y_salta_la_cuenta_activa():
    """Función pura: orden del pool, sin repetir ni la activa ni duplicados."""
    pool = [(PREFERIDA, "c0"), (RETRO, "c1"), (RETRO.upper(), "c1-bis"), (BUENA, "c2")]

    assert pre.candidatas(pool, PREFERIDA) == [(RETRO, "c1"), (BUENA, "c2")]
    assert pre.candidatas(pool, "nadie@example.com") == [
        (PREFERIDA, "c0"),
        (RETRO, "c1"),
        (BUENA, "c2"),
    ]


def test_pool_ausente_o_ilegible_no_aborta(tmp_path):
    """`leer_pool` es tolerante: sin pool el pre-vuelo sigue diciendo lo que pasa."""
    assert pre.leer_pool(tmp_path / "no-existe.txt") == []

    vacio = tmp_path / "vacio.txt"
    vacio.write_text("# solo comentarios\n", encoding="utf-8")
    assert pre.leer_pool(vacio) == []


def test_restaurar_preferida_es_silencioso_con_quiet(tmp_path, monkeypatch, capsys):
    """`quiet` (que el cron usa) no debe llenar el log con la charla del explorador."""
    monkeypatch.setattr(pre.ex, "credenciales_preferidas", lambda: (PREFERIDA, "clave"))
    monkeypatch.setattr(pre.ex, "cuenta_activa", lambda _b: PREFERIDA)
    logins: list[str] = []
    monkeypatch.setattr(
        pre.ex, "guardar_sesion", lambda _b, email, _p: logins.append(email) or {"estado": "login"}
    )

    pre.ex.restaurar_preferida(_bin(tmp_path), quiet=True)
    assert capsys.readouterr().out == ""
    assert logins == []  # ya era la cuenta activa: nada que rotar

    pre.ex.restaurar_preferida(_bin(tmp_path))
    assert "sesión final" in capsys.readouterr().out


def _main(tmp_path, monkeypatch, informe: dict, *, extra: tuple[str, ...] = ()) -> tuple[Path, int]:
    """Ejecuta `main()` en modo failover con `elegir_del_pool` simulado (sin MEGAcmd)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "mega-cmd").touch()  # solo comprueba que existe
    estado = tmp_path / "estado_cuentas.json"
    monkeypatch.setattr(pre, "elegir_del_pool", lambda *_a, **_k: informe)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verificar_rotacion.py",
            "--elegir-cuenta",
            "--mega-bin",
            str(bin_dir),
            "--volcado",
            str(_volcado(tmp_path)),
            "--json",
            str(estado),
            "--cuentas",
            str(_pool(tmp_path, [(BUENA, "clave-buena")])),
            *extra,
        ],
    )
    return estado, pre.main()


def test_main_con_failover_publica_el_estado_y_sale_cero(tmp_path, monkeypatch, capsys):
    """Fallo elegido: rc=0 y `estado_cuentas.json` con la cuenta que ve la biblioteca."""
    informe = {
        "ok": True,
        "cuenta": BUENA,
        "causa": None,
        "biblioteca": {"etiquetas": [SHARE], "titulos": 2, "files": 2, "rutas": [RUTA]},
        "inshares_montados": [RUTA],
        "buckets_vistos": {RUTA: 2},
        "faltan_rutas": [],
        "faltan_buckets": {},
        "modo": "elegir_cuenta",
        "cuenta_anterior": PREFERIDA,
        "elegida": BUENA,
        "origen": "pool",
        "candidatas": [{"email": BUENA, "login": "login", "ok": True}],
        "pool": {"fichero": "pool.txt", "cuentas": [BUENA]},
    }

    estado, rc = _main(tmp_path, monkeypatch, informe)

    assert rc == pre.EXIT_OK
    assert json.loads(estado.read_text(encoding="utf-8"))["elegida"] == BUENA
    salida = capsys.readouterr().out
    assert "cuenta elegida: dts.02.swch@gmail.com (origen=pool)" in salida


def test_main_con_failover_publica_el_fallo_y_sale_ocho(tmp_path, monkeypatch, capsys):
    """Sin cuenta válida: rc=8 y el estado queda escrito para que la UI avise."""
    informe = {
        "ok": False,
        "cuenta": PREFERIDA,
        "causa": "inshare_ausente",
        "veredicto": f"la sesión de MEGAcmd NO monta el in-share de la biblioteca: {RUTA}",
        "biblioteca": {"etiquetas": [SHARE], "titulos": 2, "files": 2, "rutas": [RUTA]},
        "inshares_montados": [],
        "buckets_vistos": {},
        "nube_propia": {"entradas": 1, "nombres": ["Importaciones MEGA"]},
        "faltan_rutas": [RUTA],
        "faltan_buckets": {},
        "modo": "elegir_cuenta",
        "cuenta_anterior": PREFERIDA,
        "elegida": None,
        "origen": None,
        "candidatas": [{"email": BUENA, "login": "login", "ok": False}],
        "pool": {"fichero": "pool.txt", "cuentas": [BUENA]},
    }

    estado, rc = _main(tmp_path, monkeypatch, informe)

    assert rc == pre.EXIT_BIBLIOTECA_DISTINTA
    cuerpo = json.loads(estado.read_text(encoding="utf-8"))
    assert cuerpo["ok"] is False and cuerpo["faltan_rutas"] == [RUTA]
    assert "ninguna cuenta del pool ve la biblioteca" in capsys.readouterr().out
