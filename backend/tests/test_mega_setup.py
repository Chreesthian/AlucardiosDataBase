"""Tests de la configuración MEGA y de la actualización lanzada desde la UI."""

from __future__ import annotations

import stat
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.mega_setup import (
    HostMegaRunner,
    MegaCredentialStore,
    MegaCuenta,
    MegaSetupInvalid,
    MegaSetupService,
    MegaUpdateBusy,
    MegaUpdateFailed,
    MegaUpdateManager,
    normalizar_cuentas,
)

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP

ROOT = Path(__file__).resolve().parents[2]
for _ruta in (ROOT, ROOT / "scripts", ROOT / "backend"):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))

import verificar_rotacion as vr  # noqa: E402  (script host reutilizado)


def _cuentas() -> list[MegaCuenta]:
    return [
        MegaCuenta("uno@example.com", "secreto-uno"),
        MegaCuenta("dos@example.com", "secreto-dos"),
        MegaCuenta("tres@example.com", "secreto-tres"),
    ]


class FakeRunner:
    """Runner determinista: no toca MEGA ni la BD real."""

    def __init__(self, *, espera: threading.Event | None = None, error: str | None = None):
        self.espera = espera
        self.error = error
        self.usado = False

    def available(self):
        return True, None

    def run(self, *, progress, secrets):
        self.usado = True
        progress("verificando", "Comprobando cuentas…")
        if self.espera is not None:
            self.espera.wait(timeout=5)
        if self.error:
            raise MegaUpdateFailed(self.error)
        return {
            "cuenta": "uno@example.com",
            "resumen": {"added_files": 2, "removed_files": 0, "changed_files": 1},
        }


def _esperar(condicion, timeout: float = 3.0) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return
        time.sleep(0.01)
    raise AssertionError("la condición no se cumplió a tiempo")


def test_store_guarda_pool_privado_y_no_expone_contrasenas(tmp_path):
    pool = tmp_path / "mega_cuentas.txt"
    env = tmp_path / "mega.env"
    store = MegaCredentialStore(pool, env)

    store.save(_cuentas())

    assert store.emails() == [
        "uno@example.com",
        "dos@example.com",
        "tres@example.com",
    ]
    assert [c.password for c in store.load()] == [
        "secreto-uno",
        "secreto-dos",
        "secreto-tres",
    ]
    assert stat.S_IMODE(pool.stat().st_mode) == 0o600
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "MEGA_EMAIL=uno@example.com" in env.read_text(encoding="utf-8")


def test_normalizar_exige_tres_cuentas_unicas_y_validas():
    with pytest.raises(MegaSetupInvalid):
        normalizar_cuentas(_cuentas()[:2])
    with pytest.raises(MegaSetupInvalid):
        normalizar_cuentas([_cuentas()[0], _cuentas()[0], _cuentas()[2]])
    with pytest.raises(MegaSetupInvalid):
        normalizar_cuentas(
            [MegaCuenta("sin-arroba", "x"), _cuentas()[1], _cuentas()[2]]
        )
    with pytest.raises(MegaSetupInvalid):
        normalizar_cuentas(
            [MegaCuenta("uno@example.com", "salto\nlinea"), _cuentas()[1], _cuentas()[2]]
        )


def test_manager_publica_estado_sin_contrasenas(tmp_path):
    store = MegaCredentialStore(tmp_path / "pool.txt", tmp_path / "mega.env")
    store.save(_cuentas())
    state = tmp_path / "actualizacion.json"
    manager = MegaUpdateManager(store, FakeRunner(), state)

    manager.start()
    _esperar(lambda: manager.status()["estado"] == "ok")

    status = manager.status()
    assert status["cuenta"] == "uno@example.com"
    assert status["resumen"]["added_files"] == 2
    texto = state.read_text(encoding="utf-8")
    assert "secreto-uno" not in texto
    assert "secreto-dos" not in texto
    assert "secreto-tres" not in texto


def test_manager_no_permite_dos_actualizaciones(tmp_path):
    store = MegaCredentialStore(tmp_path / "pool.txt", tmp_path / "mega.env")
    store.save(_cuentas())
    espera = threading.Event()
    manager = MegaUpdateManager(
        store, FakeRunner(espera=espera), tmp_path / "actualizacion.json"
    )
    manager.start()
    with pytest.raises(MegaUpdateBusy):
        manager.start()
    espera.set()
    _esperar(lambda: manager.status()["estado"] == "ok")


def test_manager_registra_fallo_sin_tocar_la_bd(tmp_path):
    store = MegaCredentialStore(tmp_path / "pool.txt", tmp_path / "mega.env")
    store.save(_cuentas())
    manager = MegaUpdateManager(
        store,
        FakeRunner(error="Las cuentas no ven la biblioteca."),
        tmp_path / "actualizacion.json",
    )
    manager.start()
    _esperar(lambda: manager.status()["estado"] == "error")
    assert manager.status()["error"] == "Las cuentas no ven la biblioteca."


def test_api_guarda_cuentas_y_no_devuelve_contrasenas(tmp_path):
    app = build_app(tmp_path)
    app.state.mega_setup = MegaSetupService(
        app.state.settings, app.state.engine, runner=FakeRunner()
    )
    payload = {
        "cuentas": [
            {"email": c.email, "password": c.password}
            for c in _cuentas()
        ]
    }
    with TestClient(app) as client:
        inicial = client.get("/api/setup/mega")
        assert inicial.status_code == 200
        assert inicial.json()["disponible"] is True
        assert inicial.json()["cuentas"] == []

        respuesta = client.post("/api/setup/mega/update", json=payload)
        assert respuesta.status_code == 202
        assert "secreto-uno" not in respuesta.text

        _esperar(
            lambda: client.get("/api/setup/mega").json()["actualizacion"]["estado"]
            == "ok"
        )
        final = client.get("/api/setup/mega")
        assert final.status_code == 200
        assert len(final.json()["cuentas"]) == 3
        assert "secreto-uno" not in final.text
        assert "secreto-dos" not in final.text
        assert final.json()["actualizacion"]["cuenta"] == "uno@example.com"


def test_api_rechaza_cuentas_invalidas_sin_eco_de_contrasenas(tmp_path):
    app = build_app(tmp_path)
    app.state.mega_setup = MegaSetupService(
        app.state.settings, app.state.engine, runner=FakeRunner()
    )
    with TestClient(app) as client:
        dos = {
            "cuentas": [
                {"email": "uno@example.com", "password": "secreto-uno"},
                {"email": "dos@example.com", "password": "secreto-dos"},
            ]
        }
        respuesta = client.post("/api/setup/mega/update", json=dos)
        assert respuesta.status_code == 400
        assert "secreto-uno" not in respuesta.text

        # Un cuerpo mal tipado no debe reproducir la contraseña en el 422.
        malo = {
            "cuentas": [
                {"email": "uno@example.com", "password": "secreto-uno"},
                {"email": "dos@example.com", "password": 123},
                {"email": "tres@example.com", "password": "secreto-tres"},
            ]
        }
        respuesta = client.post("/api/setup/mega/update", json=malo)
        assert respuesta.status_code == 422
        assert "secreto-uno" not in respuesta.text
        assert "secreto-dos" not in respuesta.text


def test_api_no_disponible_no_escribe_cuentas(tmp_path):
    """En un contenedor sin MEGAcmd no se guardan secretos ni se simula el update."""
    app = build_app(tmp_path)
    pool = tmp_path / "mega_cuentas.txt"
    with TestClient(app) as client:
        estado = client.get("/api/setup/mega")
        assert estado.status_code == 200
        assert estado.json()["disponible"] is False
        assert pool.exists() is False

        respuesta = client.post(
            "/api/setup/mega/update",
            json={
                "cuentas": [
                    {"email": "uno@example.com", "password": "secreto-uno"},
                    {"email": "dos@example.com", "password": "secreto-dos"},
                    {"email": "tres@example.com", "password": "secreto-tres"},
                ]
            },
        )
        assert respuesta.status_code == 503
        assert "secreto-uno" not in respuesta.text
        assert pool.exists() is False


def test_login_preferida_respeta_la_credencial_marcada(tmp_path):
    pool = tmp_path / "cuentas.txt"
    pool.write_text(
        "uno@example.com\tsecreto-uno\ndos@example.com\tsecreto-dos\n",
        encoding="utf-8",
    )
    env = tmp_path / "mega.env"
    env.write_text(
        "MEGA_EMAIL=dos@example.com\nMEGA_PASSWORD=secreto-dos\n",
        encoding="utf-8",
    )
    llamadas: list[str] = []

    def iniciar(mega_bin, email, password):
        llamadas.append(email)
        return {"estado": "login"}

    resultado = vr.login_preferida(
        tmp_path / "mega-bin",
        pool,
        preferred_path=env,
        iniciar=iniciar,
        quiet=True,
    )

    assert llamadas == ["dos@example.com"]
    assert resultado is not None
    assert resultado["email"] == "dos@example.com"


def test_host_runner_orquesta_scripts_y_aplica_sync(tmp_path):
    """Integración del runner con el pipeline real, usando scripts falsos."""
    app = build_app(tmp_path)
    engine = app.state.engine
    cfg = Settings(
        database_url=app.state.database_url,
        dump_path=tmp_path / "dump.txt",
        mega_scripts_dir=tmp_path / "scripts",
        mega_bin_dir=tmp_path / "mega-bin",
        mega_cuentas_path=tmp_path / "mega_cuentas.txt",
        mega_env_path=tmp_path / "mega.env",
        estado_cuentas_path=tmp_path / "estado_cuentas.json",
        actualizacion_estado_path=tmp_path / "actualizacion_estado.json",
        actualizacion_log_path=tmp_path / "actualizacion.log",
        mega_update_timeout_s=30,
    )
    origen = tmp_path / "origen.txt"
    origen.write_text(SAMPLE_DUMP, encoding="utf-8")
    cfg.resolved_dump.write_text(SAMPLE_DUMP, encoding="utf-8")

    scripts = cfg.resolved_mega_scripts
    scripts.mkdir()
    (scripts.parent / "build_megacmd_dump.py").write_text("", encoding="utf-8")
    cfg.resolved_mega_bin.mkdir(parents=True)
    (cfg.resolved_mega_bin / "mega-cmd").write_text("", encoding="utf-8")
    (scripts / "verificar_rotacion.py").write_text(
        textwrap.dedent(
            """
            import json, pathlib, sys
            args = sys.argv[1:]
            destino = args[args.index("--json") + 1]
            pathlib.Path(destino).write_text(json.dumps({
                "ok": True,
                "cuenta": "uno@example.com",
                "veredicto": "ok",
                "biblioteca": {"files": 6},
            }), encoding="utf-8")
            """
        ),
        encoding="utf-8",
    )
    (scripts / "refrescar_volcado.py").write_text(
        textwrap.dedent(
            f"""
            import pathlib, shutil, sys
            args = sys.argv[1:]
            destino = args[args.index("--out") + 1]
            shutil.copyfile({str(origen)!r}, destino)
            """
        ),
        encoding="utf-8",
    )

    store = MegaCredentialStore(cfg.resolved_mega_cuentas, cfg.resolved_mega_env)
    store.save(_cuentas())
    runner = HostMegaRunner(cfg, engine)
    assert runner.available() == (True, None)
    manager = MegaUpdateManager(store, runner, cfg.resolved_actualizacion_estado)
    manager.start()
    _esperar(lambda: manager.status()["estado"] == "ok", timeout=10)

    estado = manager.status()
    assert estado["cuenta"] == "uno@example.com"
    assert estado["resumen"]["total_files"] == 6
    assert "secreto-uno" not in cfg.resolved_actualizacion_log.read_text(
        encoding="utf-8"
    )


def test_login_preferida_usa_la_primera_cuenta_del_pool(tmp_path):
    pool = tmp_path / "cuentas.txt"
    pool.write_text(
        "uno@example.com\tsecreto-uno\ndos@example.com\tsecreto-dos\n",
        encoding="utf-8",
    )
    llamadas: list[tuple[str, str, str]] = []

    def iniciar(mega_bin, email, password):
        llamadas.append((str(mega_bin), email, password))
        return {"estado": "login", "detalle": "ok"}

    resultado = vr.login_preferida(
        tmp_path / "mega-bin",
        pool,
        iniciar=iniciar,
        quiet=True,
    )

    assert llamadas == [
        (str(tmp_path / "mega-bin"), "uno@example.com", "secreto-uno")
    ]
    assert resultado is not None
    assert resultado["email"] == "uno@example.com"
    assert resultado["estado"] == "login"
