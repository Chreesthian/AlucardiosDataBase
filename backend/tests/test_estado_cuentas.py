"""Pre-vuelo de rotación expuesto en la API (`GET /api/sync/cuentas`).

El informe lo escribe el host (`scripts/verificar_rotacion.py`, vía
`make volcado`) y vive fuera de la BD: en el host, en `data/estado_cuentas.json`
(copiada al contenedor en solo lectura). Dos contratos que la UI necesita:

1. Un informe ausente o ilegible NO es un fallo del pipeline: se responde 200 con
   `disponible=False`. Alarmar por ello daría un aviso permanente a quien usa
   `ALUCARD_PREFLIGHT=0`.
2. Un informe que dice que las credenciales de la semana montan OTRA biblioteca
   (`ok=False`) llega con el motivo y lo que falta (`faltan_rutas`,
   `faltan_buckets`) para poder explicárselo al operador sin abrir el JSON.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:  # el pre-vuelo vive en scripts/
    sys.path.insert(0, str(REPO / "scripts"))

import verificar_rotacion as pre  # noqa: E402

SHARE = "INSHARE jorgetorralba544@gmail.com:BCKP2"
RUTA = "//from/jorgetorralba544@gmail.com:BCKP2"


def _informe(**extra) -> dict:
    """Informe con la forma exacta que escribe `scripts/verificar_rotacion.py`."""
    base = {
        "generado_en": (datetime.now(UTC) - timedelta(hours=3)).isoformat(timespec="seconds"),
        "herramienta": "scripts/verificar_rotacion.py (mega-mount + mega-ls, sin listar el árbol)",
        "ok": True,
        "causa": None,
        "veredicto": f"la sesión ve la biblioteca del volcado ({SHARE}): 31608 archivos",
        "forzado": False,
        "cuenta": "dts.02.swch@gmail.com",
        "volcado": "/host/mega_cuenta_contenido_MEGAcmd.txt",
        "volcado_existe": True,
        "biblioteca": {
            "etiquetas": [SHARE],
            "rutas": [RUTA],
            "titulos": 5494,
            "files": 31608,
            "buckets_esperados": 27,
        },
        "inshares_montados": [RUTA],
        "buckets_vistos": {RUTA: 27},
        # Nube personal de la cuenta (no entra al catálogo, solo se cuenta).
        "nube_propia": {"entradas": 2, "nombres": ["Importaciones MEGA", "MEGA"]},
        "faltan_rutas": [],
        "faltan_buckets": {},
    }
    return base | extra


def _app(tmp_path, informe: dict | None = None, *, crudo: str | None = None):
    """App con `estado_cuentas_path` en el tmp (o sin informe, si no se pasa ninguno)."""
    estado = tmp_path / "estado_cuentas.json"
    if informe is not None:
        estado.write_text(json.dumps(informe, ensure_ascii=False), encoding="utf-8")
    if crudo is not None:
        estado.write_text(crudo, encoding="utf-8")
    cfg = Settings(
        database_url=f"sqlite:///{tmp_path / 'cuentas.db'}",
        estado_cuentas_path=estado,
    )
    return create_app(cfg)


def test_sin_informe_no_es_un_fallo(tmp_path):
    """Pre-vuelo desactivado o aún sin ejecutar: 200, sin alarmar a la UI."""
    with TestClient(_app(tmp_path)) as c:
        r = c.get("/api/sync/cuentas")
    assert r.status_code == 200
    body = r.json()
    assert body["disponible"] is False
    assert body["ok"] is True  # el banner NO debe dispararse por ausencia
    assert body["forzado"] is False
    assert body["cuenta"] is None
    assert body["faltan_rutas"] == [] and body["faltan_buckets"] == {}
    assert "make volcado" in body["aviso"]  # dice dónde se genera el informe


def test_informe_correcto_se_publica(tmp_path):
    with TestClient(_app(tmp_path, _informe())) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["disponible"] is True
    assert body["ok"] is True
    assert body["causa"] is None
    assert body["cuenta"] == "dts.02.swch@gmail.com"
    assert body["volcado"] == "/host/mega_cuenta_contenido_MEGAcmd.txt"
    assert body["biblioteca"]["titulos"] == 5494
    assert body["biblioteca"]["etiquetas"] == [SHARE]
    assert body["aviso"] is None  # nada que explicar: la biblioteca es la misma
    assert body["edad_horas"] == pytest.approx(3.0, abs=0.2)


def test_otra_biblioteca_llega_con_motivo_y_faltantes(tmp_path):
    """El caso de la rotación mala: rc=8 del host → la UI puede explicarlo."""
    informe = _informe(
        ok=False,
        causa="inshare_ausente",
        veredicto=f"la sesión de MEGAcmd NO monta el in-share de la biblioteca: {RUTA}",
        faltan_rutas=[RUTA],
    )
    with TestClient(_app(tmp_path, informe)) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["ok"] is False
    assert body["causa"] == "inshare_ausente"
    assert body["faltan_rutas"] == [RUTA]
    assert body["aviso"] == informe["veredicto"]  # el veredicto del host se conserva
    assert body["forzado"] is False


def test_buckets_ausentes_llegan_a_la_ui(tmp_path):
    """Share re-compartido a medias: se ve qué buckets faltan, no solo que falla."""
    informe = _informe(
        ok=False,
        causa="buckets_ausentes",
        veredicto=f"la raíz de {RUTA} no muestra 2 bucket(s) conocidos (p. ej. -- A, -- B)",
        faltan_buckets={RUTA: ["-- A", "-- B"]},
    )
    with TestClient(_app(tmp_path, informe)) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["ok"] is False
    assert body["faltan_buckets"] == {RUTA: ["-- A", "-- B"]}
    assert "-- A" in body["aviso"]


def test_sin_sesion_se_explica_sin_mentir(tmp_path):
    """Sin sesión MEGA el veredicto se sustituye: no se culpa a las credenciales."""
    informe = _informe(
        ok=False,
        causa="sin_sesion",
        veredicto="no hay sesión MEGAcmd activa: no se puede verificar la biblioteca",
        cuenta=None,
    )
    with TestClient(_app(tmp_path, informe)) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["ok"] is False
    assert body["causa"] == "sin_sesion"
    assert body["cuenta"] is None
    assert "no hay sesión" in body["aviso"].lower()


def test_forzado_se_publica_tal_cual(tmp_path):
    """`--permitir-otra-biblioteca` es una decisión consciente: la UI decide."""
    informe = _informe(ok=False, causa="inshare_ausente", forzado=True, faltan_rutas=[RUTA])
    with TestClient(_app(tmp_path, informe)) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["disponible"] is True
    assert body["ok"] is False
    assert body["forzado"] is True  # sin `forzado` esto sería un banner de alarma


def test_informe_a_medias_tolera_claves_ausentes(tmp_path):
    """Un informe escrito por una versión antigua no puede romper el endpoint."""
    with TestClient(_app(tmp_path, {"ok": True})) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["disponible"] is True
    assert body["ok"] is True
    assert body["cuenta"] is None and body["generado_en"] is None
    assert body["edad_horas"] is None
    assert body["biblioteca"] is None


@pytest.mark.parametrize("crudo", ["{no es json", "[]", "null", "", "123"])
def test_informe_ilegible_no_rompe_el_endpoint(tmp_path, crudo):
    with TestClient(_app(tmp_path, crudo=crudo)) as c:
        r = c.get("/api/sync/cuentas")
    assert r.status_code == 200
    assert r.json()["disponible"] is False


def test_informe_con_tipos_raros_no_rompe_el_endpoint(tmp_path):
    """Campos con el tipo equivocado se sanean en vez de reventar el modelo."""
    informe = _informe(faltan_rutas="//from/x", faltan_buckets=[RUTA], biblioteca="nope")
    with TestClient(_app(tmp_path, informe)) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["disponible"] is True
    assert body["faltan_rutas"] == []
    assert body["faltan_buckets"] == {}
    assert body["biblioteca"] is None


def test_ruta_del_informe_por_defecto_va_junto_a_la_bd(tmp_path):
    """En el host el informe vive junto a la BD; en Docker se apunta con la env var."""
    por_defecto = Settings(db_path=tmp_path / "datos" / "alucard.db")
    assert por_defecto.resolved_estado_cuentas == tmp_path / "datos" / "estado_cuentas.json"

    # Sin `db_path` (valor por defecto del repo) sigue siendo `data/estado_cuentas.json`.
    del_repo = Settings()
    assert del_repo.resolved_estado_cuentas.name == "estado_cuentas.json"
    assert del_repo.resolved_estado_cuentas.parent.name == "data"

    explicito = Settings(estado_cuentas_path=tmp_path / "otro" / "estado.json")
    assert explicito.resolved_estado_cuentas == tmp_path / "otro" / "estado.json"


def test_nube_propia_de_la_cuenta_llega_a_la_ui(tmp_path):
    """La UI puede decir cuántas entradas quedan fuera de la biblioteca."""
    with TestClient(_app(tmp_path, _informe())) as c:
        body = c.get("/api/sync/cuentas").json()

    assert body["nube_propia"] == {"entradas": 2, "nombres": ["Importaciones MEGA", "MEGA"]}

    # Un informe de una versión anterior no trae el campo: sigue siendo válido.
    informe = _informe()
    del informe["nube_propia"]
    with TestClient(_app(tmp_path, informe)) as c:
        body = c.get("/api/sync/cuentas").json()
    assert body["nube_propia"] is None and body["disponible"] is True


def test_nube_propia_del_pre_vuelo_ignora_las_carpetas_internas():
    """`verificar_rotacion.nube_propia` cuenta lo del operador y nada más."""
    assert pre.nube_propia([]) == {"entradas": 0, "nombres": []}
    listado = ["S4 Object storage", "Importaciones MEGA/", "MEGA", "Importaciones MEGA/"]

    solo_operador = pre.nube_propia(listado, interno=pre.NUBE_INTERNA)

    assert solo_operador["entradas"] == 3  # la carpeta interna no cuenta
    assert solo_operador["nombres"] == ["Importaciones MEGA/", "MEGA", "Importaciones MEGA/"]
    # El informe no crece sin límite: solo se guardan los primeros nombres.
    muchos = pre.nube_propia([f"carpeta-{i}" for i in range(25)])
    assert muchos["entradas"] == 25 and len(muchos["nombres"]) == pre.NUBE_NOMBRES
