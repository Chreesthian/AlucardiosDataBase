"""El contenido propio de la cuenta de turno NO es biblioteca (ni catálogo).

Las credenciales MEGA rotan cada semana y el volcado canónico incluye los sectores
de la CUENTA que lo generó (CLOUD_DRIVE, INBOX, RUBBISH_BIN) además del in-share
con la biblioteca. Esos sectores propios cambian con la cuenta: el caso real es
`dts.02.swch@gmail.com` (nube vacía) frente a `dts.03.swch@gmail.com` (misma
biblioteca, in-share idéntico, pero su nube trae vídeos personales). Si entraran
al catálogo, cada rotación añadiría y borraría nodos ajenos, desplazaría los
totales publicados (`/api/meta`) y registraría falsos "juego nuevo" en Novedades.

Contrato fijado aquí:

1. la ingesta completa (bootstrap) indexa solo los sectores de la biblioteca y sus
   totales describen el catálogo,
2. el escaneo incremental ignora esos sectores (y lo reporta en el resumen), así
   que rotar la cuenta es un no-op,
3. una BD que ya tuviera ruido de una rotación anterior se limpia en el siguiente
   escaneo, sin generar eventos,
4. ni siquiera el registro de "Novedades" puede crear eventos con rutas fuera de un
   bucket de la biblioteca.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Node, Novedad, Snapshot, Title
from app.novedades import registrar_novedades, titulo_de
from app.parser import FILE, es_biblioteca, parse_text
from app.parser import Node as PNode
from app.sync import refresh_text

from .conftest import build_app
from .sample_dump import SAMPLE_DUMP

SHARE = "INSHARE test@example.com:BCKP1"

# Bloque interior de la nube personal en el volcado de muestra (vacía: solo la
# carpeta interna de MEGAcmd) y el mismo con dos vídeos personales de la cuenta.
NUBE_VACIA_SAMPLE = (
    "Archivos  : 0\n"
    "Carpetas  : 1\n"
    "Tamano    : 0 bytes (0 B)\n"
    "\n"
    "[ROOT] //\n"
    "`-- [FOLDER] S4 Object storage/\n"
)
NUBE_CON_ARCHIVOS = (
    "Archivos  : 2\n"
    "Carpetas  : 2\n"
    "Tamano    : 274740918 bytes (262.02 MiB)\n"
    "\n"
    "[ROOT] //\n"
    "|-- [FOLDER] Importaciones MEGA/\n"
    "|   |-- [FILE] 4410_13_SUB.mp4  (109192712 bytes)\n"
    "|   `-- [FILE] 4412_13_SUB.mp4  (164732633 bytes)\n"
    "`-- [FOLDER] MEGA/\n"
)


def _con_nube_poblada(texto: str, cuenta: str = "semana.nueva@example.com") -> str:
    """El mismo volcado con la nube personal de OTRA cuenta de la rotación."""
    return texto.replace(NUBE_VACIA_SAMPLE, NUBE_CON_ARCHIVOS).replace(
        "Cuenta            : test@example.com", f"Cuenta            : {cuenta}"
    )


DUMP_NUBE_VACIA = SAMPLE_DUMP
DUMP_NUBE_LLENA = _con_nube_poblada(SAMPLE_DUMP)


def _fuera_biblioteca(engine) -> list[str]:
    """Rutas del catálogo que no son de la biblioteca (deberían ser ninguna)."""
    with Session(engine) as s:
        return sorted(
            n.path for n in s.execute(select(Node)).scalars() if not n.path.startswith(SHARE)
        )


def test_es_biblioteca_solo_los_inshares():
    """Criterio único: el in-share es la biblioteca; lo demás es la cuenta."""
    assert es_biblioteca(SHARE) is True
    assert es_biblioteca("  INSHARE otra@example.com:CARPETA  ") is True
    for etiqueta in ("CLOUD_DRIVE", "INBOX", "RUBBISH_BIN", "INSHARE"):  # sin espacio
        assert es_biblioteca(etiqueta) is False


def test_totales_del_volcado_se_pueden_limitar_a_la_biblioteca():
    """`ParsedDump.totals(sectores=…)` aísla la biblioteca de la nube personal."""
    parsed = parse_text(DUMP_NUBE_LLENA)
    completo = parsed.totals()
    biblioteca = parsed.totals(sectores=parsed.sectores_biblioteca())

    assert parsed.sectores_biblioteca() == [SHARE]
    assert completo["files"] == 8  # 6 de la biblioteca + 2 vídeos personales
    assert biblioteca["files"] == 6
    assert biblioteca["folders"] < completo["folders"]  # la nube aporta carpetas
    assert biblioteca["size"] < completo["size"]


def test_bootstrap_solo_indexa_la_biblioteca(tmp_path):
    """Primera ingesta: el catálogo nace sin el contenido propio de la cuenta."""
    app = build_app(tmp_path, DUMP_NUBE_LLENA)
    engine = app.state.engine

    with Session(engine) as s:
        snap = s.execute(select(Snapshot).order_by(Snapshot.id.desc())).scalars().first()
        assert snap.file_count == 6  # los 6 de la biblioteca, no los 8 del volcado
        assert {t.name for t in s.execute(select(Title)).scalars()} == {
            "A Game One",
            "A Second Game",
            "Zelda Echoes of Wisdom",
        }
        assert any(n.role == "title" for n in s.execute(select(Node)).scalars())

    assert _fuera_biblioteca(engine) == []


def test_rotar_la_cuenta_con_nube_poblada_no_mueve_el_catalogo(tmp_path):
    """Rotación real (misma biblioteca, nube propia con contenido): no-op."""
    app = build_app(tmp_path, DUMP_NUBE_VACIA)
    engine = app.state.engine
    with Session(engine) as s:
        antes = {t.slug for t in s.execute(select(Title)).scalars()}
        snap_antes = s.execute(select(Snapshot).order_by(Snapshot.id.desc())).scalars().first()
        files_antes = snap_antes.file_count

    stats = refresh_text(engine, DUMP_NUBE_LLENA)

    assert stats["added_files"] == 0
    assert stats["removed_files"] == 0
    assert stats["added_folders"] == 0
    assert stats["novedades"] == 0
    assert stats["ignorados_fuera_biblioteca"]["CLOUD_DRIVE"]["files"] == 2
    # Los totales publicados siguen siendo los del catálogo, no los del volcado.
    assert stats["total_files"] == files_antes == 6
    assert stats["total_files_volcado"] == 8

    with Session(engine) as s:
        assert {t.slug for t in s.execute(select(Title)).scalars()} == antes
        snap = s.execute(select(Snapshot).order_by(Snapshot.id.desc())).scalars().first()
        assert snap.account == "semana.nueva@example.com"  # la cabecera sí se refresca
        assert snap.file_count == 6
        assert s.execute(select(Novedad)).scalars().all() == []

    assert _fuera_biblioteca(engine) == []


def test_el_ruido_de_una_rotacion_anterior_se_limpia(tmp_path):
    """Una BD con nodos de la nube personal los pierde en el siguiente escaneo."""
    app = build_app(tmp_path, DUMP_NUBE_VACIA)
    engine = app.state.engine

    with Session(engine) as s:
        sid = s.execute(select(Snapshot.id).order_by(Snapshot.id.desc())).scalars().first()
        # Ruido de una rotación anterior con la nube poblada.
        s.add(
            Node(
                snapshot_id=sid,
                path="CLOUD_DRIVE/Importaciones MEGA/4410_13_SUB.mp4",
                name="4410_13_SUB.mp4",
                depth=2,
                kind="file",
                role="",
                ext="mp4",
                size=109192712,
                node_order=99999,
            )
        )
        s.commit()

    assert len(_fuera_biblioteca(engine)) == 1

    stats = refresh_text(engine, DUMP_NUBE_VACIA)

    assert stats["removed_files"] == 1  # el vídeo personal
    assert stats["added_files"] == 0
    assert stats["novedades"] == 0
    assert _fuera_biblioteca(engine) == []


def test_titulo_de_exige_biblioteca_y_bucket():
    """Solo las rutas de un bucket de la biblioteca son "título"."""
    assert titulo_de(f"{SHARE}/-- A/A Game One/B-ASE/game1.part1.rar") == (
        f"{SHARE}/-- A/A Game One"
    )
    assert titulo_de("CLOUD_DRIVE/Importaciones MEGA/4410_13_SUB.mp4") is None
    assert titulo_de("INBOX/Backups/foo.rar") is None
    assert titulo_de(f"{SHARE}/S4 Object storage/video.mp4") is None  # sin bucket
    assert titulo_de(f"{SHARE}/-- A") is None  # sin título


def test_novedades_no_crea_eventos_fuera_de_la_biblioteca(tmp_path):
    """`registrar_novedades` descarta rutas ajenas (defensa del histórico)."""
    app = build_app(tmp_path, DUMP_NUBE_VACIA)
    engine = app.state.engine
    video = PNode(name="4410_13_SUB.mp4", kind=FILE, depth=2, size=109192712, ext="mp4")
    archivo = PNode(name="game1.part1.rar", kind=FILE, depth=3, size=104857600, ext="rar")
    nodos = {
        "CLOUD_DRIVE/Importaciones MEGA/4410_13_SUB.mp4": video,
        f"{SHARE}/-- A/A Game One/B-ASE/game1.part1.rar": archivo,
    }

    with Session(engine) as s:
        sid = s.execute(select(Snapshot.id).order_by(Snapshot.id.desc())).scalars().first()
        creados = registrar_novedades(s, sid, list(nodos), nodos)
        s.commit()

        assert creados == 1  # solo el archivo de la biblioteca
        eventos = s.execute(select(Novedad)).scalars().all()
        assert [e.slug for e in eventos] == ["a-game-one"]
        assert all("4410_13_SUB" not in (e.detalle_json or "") for e in eventos)
