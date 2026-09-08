"""Tests de descarga de archivos (enlace MEGA / fallback)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.routers.download import path_a_mega, remote_candidates

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP

RUTA = "INSHARE test@example.com:BCKP1/-- A/A Game One/B-ASE/game1.part1.rar"


def test_path_a_mega():
    assert path_a_mega("CLOUD_DRIVE/S4 Object storage") == "/S4 Object storage"
    assert path_a_mega(
        "INSHARE cuenta.base.demo@gmail.com:BCKP1/-- A/Game/x.rar"
    ) == "/from/cuenta.base.demo@gmail.com:BCKP1/-- A/Game/x.rar"
    assert path_a_mega("INSHARE cuenta.base.demo@gmail.com:BCKP1") == (
        "/from/cuenta.base.demo@gmail.com:BCKP1"
    )


def test_remote_candidates_incluyen_variantes_y_cuenta_duena():
    c = remote_candidates(RUTA)
    # 1) share montado (sintaxis MEGAcmd con `:`)
    assert c[0] == (
        "/from/test@example.com:BCKP1/-- A/A Game One/B-ASE/game1.part1.rar"
    )
    # 2) variante con `/` en lugar de `:`
    assert (
        "/from/test@example.com/BCKP1/-- A/A Game One/B-ASE/game1.part1.rar"
    ) in c
    # 3) la cuenta dueña tiene BCKP1 en la raíz de su nube
    assert "/BCKP1/-- A/A Game One/B-ASE/game1.part1.rar" in c
    assert len(c) == len(set(c))


def test_remote_candidates_raiz_del_share():
    # La propia carpeta raíz del share también ofrece la vista de dueño.
    c = remote_candidates("INSHARE test@example.com:BCKP1")
    assert c[0] == "/from/test@example.com:BCKP1"
    assert "/BCKP1" in c


def test_descarga_fallback_sin_megacmd(tmp_path):
    # mega-export no existe en el entorno de tests → redirige al sitio MEGA.
    app = build_app(tmp_path, SAMPLE_DUMP)
    with TestClient(app) as c:
        r = c.get("/api/download", params={"path": RUTA}, follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers.get("location", "").startswith("https://mega.nz")


def test_descarga_con_enlace_mega(tmp_path, monkeypatch):
    app = build_app(tmp_path, SAMPLE_DUMP)

    class _Fake:
        @staticmethod
        def export_link(remote):  # noqa: D102
            return "https://mega.nz/file/ABCDEF#clave123"

    monkeypatch.setattr("app.routers.download.megacmd", _Fake)
    with TestClient(app) as c:
        r = c.get("/api/download", params={"path": RUTA}, follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://mega.nz/file/ABCDEF#clave123"


def test_descarga_archivo_inexistente(tmp_path):
    app = build_app(tmp_path, SAMPLE_DUMP)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/download", params={"path": "INSHARE x/no-existe.rar"})
    assert r.status_code == 404
