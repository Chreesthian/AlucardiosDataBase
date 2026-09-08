#!/usr/bin/env bash
# =============================================================================
# enlazar_descargas.sh — Genera los enlaces MEGA reales (1:1 por nodo) para toda
# la biblioteca y los guarda en `downloads` (caché) + `data/descargas.json`.
#
# CUÁNDO USARLO:
#   - Cuando una cuenta MEGA activa tenga los nodos (share entrante montado en
#     `/from/…:BCKP1` o la cuenta dueña con `/BCKP1` en su nube).
#
# QUÉ HACE:
#   1. Comprueba que exista una raíz alcanzable (`/from` o `/BCKP1`).
#   2. Para la API, copia la BD del contenedor a una copia local segura.
#   3. Ejecuta `app.indexar_descargas --nivel todos` (reanudable: solo pide lo
#      `pendiente`/`error`) contra esa copia usando MEGAcmd del host.
#   4. Devuelve la BD con el caché completo al contenedor y lo reinicia.
#
# USO:
#   ./scripts/enlazar_descargas.sh                 # todos los nodos
#   ./scripts/enlazar_descargas.sh --limite 5      # prueba rápida (5 nodos)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEGA_BIN="${MEGA_BIN:-/home/christian/opt/megacmd/usr/bin}"
export PATH="$MEGA_BIN:$PATH"
export HOME="${HOME:-/home/christian}"

LIMITE=""
FORCE="${FORCE:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limite) LIMITE="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    *) echo "Argumento desconocido: $1"; exit 2 ;;
  esac
done

echo "── 1/5 Preflight: raíz MEGA alcanzable ──────────────────────────────"
FROM_OK=$(timeout 20 mega-ls /from 2>/dev/null | head -3 || true)
BCKP_OK=$(timeout 20 mega-ls /BCKP1 2>/dev/null | head -3 || true)
if [[ -z "$FROM_OK" && -z "$BCKP_OK" ]]; then
  echo "⚠  No hay ninguna raíz con los nodos (/from ni /BCKP1)."
  echo "   → Re-monta el share en la cuenta activa o inicia sesión con la"
  echo "     cuenta dueña (BCKP1 en la raíz) y vuelve a ejecutar."
  [[ "$FORCE" == "1" ]] || exit 1
else
  echo "   /from : ${FROM_OK:-<vacío>}"
  echo "   /BCKP1: ${BCKP_OK:-<vacío>}"
fi

DB_TMP="/tmp/alucard_enlazar.db"
echo "── 2/5 Deteniendo backend para copia segura de la BD ────────────────"
docker compose -f "$ROOT/docker-compose.yaml" stop backend

echo "── 3/5 Copiando BD del contenedor → $DB_TMP ─────────────────────────"
docker compose -f "$ROOT/docker-compose.yaml" cp backend:/data/alucard.db "$DB_TMP"

echo "── 4/5 Generando enlaces (indexar_descargas) ────────────────────────"
ARGS=(--nivel todos --db "$DB_TMP" --out "$ROOT/data/descargas.json")
[[ -n "$LIMITE" ]] && ARGS+=(--limite "$LIMITE")
echo "   comando: uv run python -m app.indexar_descargas ${ARGS[*]}"
(cd "$ROOT/backend" && uv run python -m app.indexar_descargas "${ARGS[@]}")

echo "── 5/5 Devolviendo BD con caché al contenedor y arrancando ──────────"
docker compose -f "$ROOT/docker-compose.yaml" cp "$DB_TMP" backend:/data/alucard.db
docker compose -f "$ROOT/docker-compose.yaml" start backend

echo "✔  Enlaces generados. Comprueba:"
echo "   python3 -c \"import json;d=json.load(open('$ROOT/data/descargas.json'));print(d['meta'])\""
