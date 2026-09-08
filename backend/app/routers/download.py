"""Descarga de un nodo de la biblioteca (archivo o carpeta) → enlace MEGA real.

Garantías:
  - Se usa SIEMPRE la ruta del nodo exacto pulsado (nunca un ancestro): si el
    clic es sobre un archivo se exporta ESE archivo; si es sobre una carpeta
    (BASE, título, letra…), se exporta ESA carpeta.
  - El enlace generado se cachea en `downloads` (por ruta exacta) para ser
    estable/reutilizable y consultable desde el índice JSON.
  - Cabecera `X-Download-Remote` en la respuesta con la ruta MEGA real usada
    (diagnóstico para cuadrar enlaces como fm/…).
  - Fallback: sin MEGAcmd → https://mega.nz
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import megacmd
from ..deps import get_session
from ..library import current_snapshot
from ..models import DownloadLink, Node

router = APIRouter(prefix="/api", tags=["download"])

_ROOT_MEGA = {"CLOUD_DRIVE": "/", "INBOX": "/in/", "RUBBISH_BIN": "/bin/"}


def path_a_mega(path: str) -> str:
    """Traduce una ruta interna de la BD a la ruta MEGA real (1:1 con el nodo)."""
    partes = path.split("/", 1)
    sector = partes[0]
    resto = partes[1] if len(partes) > 1 else ""
    if sector.startswith("INSHARE "):
        share = sector[len("INSHARE ") :].strip()
        base = "/from/" + share
    else:
        base = _ROOT_MEGA.get(sector, "/" + sector)
    return (base.rstrip("/") + "/" + resto) if resto else base


def remote_candidates(path: str) -> list[str]:
    """Posibles rutas MEGA reales para un nodo (por si cambia la sintaxis del
    share o la sesión activa es la cuenta dueña del contenido):
      - `/from/cuenta:carpeta/…`   (share entrante montado, sintaxis MEGAcmd)
      - `/from/cuenta/carpeta/…`   (variante con `/` en lugar de `:`)
      - `/carpeta/…`               (BCKP1 en la raíz de la nube = cuenta dueña)
    """
    cand = path_a_mega(path)
    out: list[str] = [cand]
    if cand.startswith("/from/"):
        resto = cand[len("/from/") :]
        if ":" in resto:
            alt = "/from/" + resto.replace(":", "/", 1)
            if alt != cand:
                out.append(alt)
        # El contenido original también vive en la nube del dueño:
        # /from/cuenta:carpeta/… → /carpeta/…
        segs = resto.split("/")
        carpeta = segs[0].split(":", 1)[-1]
        dueño = "/" + "/".join([carpeta, *segs[1:]])
        if dueño != cand:
            out.append(dueño)
    return out


def _cachear(session: Session, snap_id: int, node: Node, link: str) -> None:
    """Guarda/actualiza el enlace del nodo exacto en el índice `downloads`."""
    fila = (
        session.execute(
            select(DownloadLink).where(
                DownloadLink.snapshot_id == snap_id, DownloadLink.path == node.path
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        session.add(
            DownloadLink(
                snapshot_id=snap_id,
                node_id=node.id,
                path=node.path,
                nivel="archivo" if node.kind == "file" else "carpeta",
                metodo="mega_export",
                estado="ok",
                link=link,
                generado_en=datetime.now(UTC),
            )
        )
    else:
        fila.link = link
        fila.estado = "ok"
        fila.error = None
        fila.generado_en = datetime.now(UTC)
    session.commit()


@router.get("/download")
def descargar(path: str, session: Session = Depends(get_session)) -> RedirectResponse:
    snap = current_snapshot(session)
    if snap is None:
        raise HTTPException(404, "No hay snapshot: ejecuta primero la ingesta.")
    node = (
        session.execute(select(Node).where(Node.snapshot_id == snap.id, Node.path == path))
        .scalars()
        .first()
    )
    if node is None:
        raise HTTPException(404, f"Nodo no encontrado: {path}")

    candidatas = remote_candidates(path)
    # 1) Enlace ya indexado para ESTA ruta exacta.
    idx = (
        session.execute(
            select(DownloadLink).where(
                DownloadLink.snapshot_id == snap.id, DownloadLink.path == path
            )
        )
        .scalars()
        .first()
    )
    link = idx.link if (idx and idx.estado == "ok" and idx.link) else None
    remoto_usado = (idx.error if idx else None) or candidatas[0]

    # 2) Si no, genera el enlace del nodo exacto (probando variantes de share)
    #    y lo cachea.
    if not link:
        link, remoto_usado = None, candidatas[0]
        for remote in candidatas:
            try:
                link = megacmd.export_link(remote)
                remoto_usado = remote
                break
            except megacmd.MegaCmdUnavailable:
                continue
        if link:
            _cachear(session, snap.id, node, link)
        else:
            resp = RedirectResponse("https://mega.nz", status_code=302)
            resp.headers["X-Download-Remote"] = remoto_usado
            return resp
    resp = RedirectResponse(link, status_code=302)
    resp.headers["X-Download-Remote"] = remoto_usado
    return resp
