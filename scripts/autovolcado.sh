#!/usr/bin/env bash
# =============================================================================
# autovolcado.sh — Refresco AUTOMÁTICO del volcado canónico MEGA + escaneo.
#
# POR QUÉ EXISTE:
#   `backend-sync` vigila el volcado, pero NO puede regenerarlo: la única fuente
#   es MEGAcmd en el host (sesión en ~/.megaCmd). Sin este refresco el vigía
#   repite "volcado sin cambios" y la BD, el catálogo y la sección "Novedades"
#   se quedan congelados EN SILENCIO. Este script cierra ese hueco y falla
#   RUIDOSO: si el refresco no se puede completar sale con código != 0 (cron
#   avisa por correo) y deja el motivo en `data/volcado.log`.
#
# QUÉ HACE:
#   1. Comprueba que hay sesión MEGAcmd activa (si no: rc=4).
#   2. Refresca el volcado con `scripts/refrescar_volcado.py` (escritura en
#      sitio, mismo inodo, con guard anti-vaciado y diff previo).
#   3. Pide el escaneo incremental a la API (`POST /api/sync/dump`) para que el
#      diff, las novedades y el export se apliquen YA (el vigía `backend-sync`
#      sigue siendo la red de seguridad: lo aplicaría en ≤300 s).
#   4. Registra el resultado en `data/volcado.log` y `data/volcado_estado.json`.
#
# USO:
#   ./scripts/autovolcado.sh                 # refresco + escaneo
#   ./scripts/autovolcado.sh --no-sync       # solo el volcado
#   ./scripts/autovolcado.sh --dry-run       # no escribe el volcado
#   ./scripts/autovolcado.sh --install-cron  # cron cada 6 h (idempotente)
#   ./scripts/autovolcado.sh --remove-cron   # quita la entrada de cron
#   ./scripts/autovolcado.sh --set-cred      # guarda las credenciales de la semana
#   ./scripts/autovolcado.sh --estado        # último resultado + logs
#
# ROTACIÓN DE CREDENCIALES (flujo normal, semanal):
#   Las cuentas MEGA cambian cada semana pero todas ven el MISMO share con la
#   biblioteca. El pipeline se ancla al SHARE (etiqueta `INSHARE <dueño>:<carpeta>`
#   del volcado), no a la cuenta:
#     · Si la sesión es de otra cuenta, se re-loguea SOLO con las credenciales
#       actuales (login primero; si falla, se RESTAURA la sesión previa y se
#       avisa con rc=4 sin dejar el host sin MEGAcmd).
#     · `refrescar_volcado.py` aborta si el candidato pierde sectores que hoy
#       traen archivos → unas credenciales sin acceso NO pueden vaciar la BD.
#     · El diff de `app.sync` es por rutas, así que rotar la cuenta sin cambios
#       reales produce 0 altas/bajas (nada de novedades fantasma ni de perder
#       el enriquecimiento IGDB).
#
# VARIABLES:
#   MEGA_BIN            binarios MEGAcmd (def. /home/christian/opt/megacmd/usr/bin)
#   MEGA_EMAIL          cuenta de la semana (o el fichero de credenciales)
#   MEGA_PASSWORD       contraseña de la semana
#   MEGA_OUT            volcado de salida (def. <repo>/mega_cuenta_contenido_MEGAcmd.txt)
#   ALUCARD_MEGA_ENV    fichero de credenciales (def. ~/.config/alucard/mega.env)
#   ALUCARD_API_URL     API del backend (def. http://127.0.0.1:<BACKEND_PORT|7331>)
#   ALUCARD_PY          intérprete con las deps del backend (def. backend/.venv/bin/python)
#   ALUCARD_CRON_HORAS  cadencia del cron instalado (def. 6)
#
# CÓDIGOS DE SALIDA: 0 ok · 4 sin sesión MEGA/credenciales · 5 fallo del volcado ·
#                    6 fallo del escaneo en la API · 7 otra ejecución en curso
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/mega_session.sh
source "$ROOT/scripts/lib/mega_session.sh"
MEGA_BIN="${MEGA_BIN:-/home/christian/opt/megacmd/usr/bin}"
ALUCARD_PY="${ALUCARD_PY:-$ROOT/backend/.venv/bin/python}"
LOG_DIR="$ROOT/data"
LOG="$LOG_DIR/volcado.log"
ESTADO="$LOG_DIR/volcado_estado.json"
CRON_TAG="# alucard-volcado (gestionado por scripts/autovolcado.sh)"
CRON_HORAS="${ALUCARD_CRON_HORAS:-6}"
CRON_LINEA="17 */${CRON_HORAS} * * * $ROOT/scripts/autovolcado.sh --quiet >> $LOG_DIR/volcado-cron.log 2>&1 $CRON_TAG"

QUIET=0
DRY_RUN=0
HACER_SYNC=1
ACCION="run"
for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --no-sync) HACER_SYNC=0 ;;
    --install-cron) ACCION="install" ;;
    --remove-cron) ACCION="remove" ;;
    --estado) ACCION="estado" ;;
    --set-cred) ACCION="set-cred" ;;
    *) echo "Argumento desconocido: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$LOG_DIR"

log() {  # log <mensaje…> — a fichero siempre; a consola si no es --quiet
  local linea="[$(date -Is)] $*"
  printf '%s\n' "$linea" >>"$LOG"
  [[ "$QUIET" == "1" ]] || printf '%s\n' "$linea"
}

corta() {  # corta <texto…> — a stderr para que cron lo reporte por correo
  printf '%s\n' "$*" >&2
}

api_url() {
  if [[ -n "${ALUCARD_API_URL:-}" ]]; then
    printf '%s' "$ALUCARD_API_URL"
    return
  fi
  local puerto
  puerto="$(grep -E '^BACKEND_PORT=' "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '"'"'"' ')"
  printf 'http://127.0.0.1:%s' "${puerto:-7331}"
}

escribir_estado() {  # escribir_estado <rc> <mensaje> <inicio> <fin>
  command -v python3 >/dev/null 2>&1 || return 0
  python3 - "$ESTADO" "$1" "$2" "$3" "$4" <<'PY'
import json
import pathlib
import sys

estado, rc, mensaje, inicio, fin = sys.argv[1:6]
pathlib.Path(estado).write_text(
    json.dumps(
        {"ok": rc == "0", "ultimo_rc": int(rc), "mensaje": mensaje, "inicio": inicio, "fin": fin},
        ensure_ascii=False,
        indent=1,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

instalar_cron() {
  local actual
  actual="$(crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true)"
  printf '%s\n%s\n' "$actual" "$CRON_LINEA" | grep -v '^$' | crontab -
  log "cron instalado (cada ${CRON_HORAS} h): $(crontab -l | grep -F "$CRON_TAG")"
}

quitar_cron() {
  local actual
  actual="$(crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true)"
  printf '%s\n' "$actual" | crontab -
  log "cron retirado (el resto de entradas queda intacto)"
}

mostrar_estado() {
  if [[ -f "$ESTADO" ]]; then cat "$ESTADO"; else echo "(sin estado: aún no se ha ejecutado)"; fi
  echo "── últimas 15 líneas de $LOG ──"
  if [[ -f "$LOG" ]]; then tail -n 15 "$LOG"; else echo "(sin log)"; fi
  echo "── crontab ──"
  crontab -l 2>/dev/null | grep -F "$CRON_TAG" || echo "(sin entrada de cron)"
}

case "$ACCION" in
  install) instalar_cron; exit 0 ;;
  remove) quitar_cron; exit 0 ;;
  estado) mostrar_estado; exit 0 ;;
  set-cred)
    read -r -p 'MEGA_EMAIL (cuenta de la semana): ' _email
    read -r -s -p 'MEGA_PASSWORD: ' _pass
    echo
    guardar_credenciales_mega "$ROOT" "$_email" "$_pass"
    unset _pass
    exit 0
    ;;
esac

# ── Run: refresco del volcado + escaneo incremental ──────────────────────────
INICIO="$(date -Is)"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOG_DIR/.volcado.lock"
  if ! flock -n 9; then
    log "AVISO: ya hay un refresco en curso (lock ocupado); nada que hacer"
    escribir_estado 7 "ya hay un refresco en curso" "$INICIO" "$(date -Is)"
    exit 7
  fi
fi

export PATH="$MEGA_BIN:$PATH"

if ! command -v mega-whoami >/dev/null 2>&1; then
  mensaje="no encuentro MEGAcmd en $MEGA_BIN; revisa MEGA_BIN"
  log "ERROR: $mensaje"
  corta "autovolcado: $mensaje"
  escribir_estado 4 "$mensaje" "$INICIO" "$(date -Is)"
  exit 4
fi

# Credenciales de la semana (rotan): entorno o fichero externo. Nunca se imprimen.
if cargar_credenciales_mega "$ROOT"; then
  log "credenciales MEGA disponibles en $MEGA_EMAIL_FUENTE para $MEGA_EMAIL"
else
  log "AVISO: sin MEGA_EMAIL/MEGA_PASSWORD (usa --set-cred): la rotación no será automática"
fi

# Rotación: re-loguea si la sesión es de otra cuenta; si el login falla, restaura
# la sesión previa para no dejar el host sin MEGAcmd.
if ! asegurar_sesion_mega; then
  mensaje="sin sesión MEGAcmd utilizable para ${MEGA_EMAIL:-la cuenta de la semana}: revisa las credenciales (${MEGA_EMAIL_FUENTE:-sin fuente})"
  corta "autovolcado: $mensaje → el volcado y la BD se quedarán congelados"
  escribir_estado 4 "$mensaje" "$INICIO" "$(date -Is)"
  exit 4
fi
CUENTA="$(cuenta_activa_mega)"
log "sesión MEGAcmd: ${CUENTA:-<ninguna>} (la biblioteca se identifica por el SHARE del volcado, no por la cuenta)"
ARGS=(--mega-bin "$MEGA_BIN")
[[ "$DRY_RUN" == "1" ]] && ARGS+=(--dry-run)
log "volcando: $ALUCARD_PY scripts/refrescar_volcado.py ${ARGS[*]}"
if ! "$ALUCARD_PY" "$ROOT/scripts/refrescar_volcado.py" "${ARGS[@]}" >>"$LOG" 2>&1; then
  rc=$?
  mensaje="el refresco del volcado falló (rc=$rc); mira $LOG"
  log "ERROR: $mensaje"
  corta "autovolcado: $mensaje → la BD y las novedades NO se actualizarán"
  escribir_estado 5 "$mensaje" "$INICIO" "$(date -Is)"
  exit 5
fi

if [[ "$HACER_SYNC" == "1" && "$DRY_RUN" != "1" ]]; then
  URL="$(api_url)"
  TMP="$(mktemp)"
  codigo="$(curl -sS -o "$TMP" -w '%{http_code}' --max-time 1800 \
            -X POST "$URL/api/sync/dump" -H 'Content-Type: application/json' -d '{}' || echo 000)"
  if [[ "$codigo" != "200" ]]; then
    mensaje="el escaneo en la API falló (HTTP $codigo en $URL/api/sync/dump): $(head -c 400 "$TMP")"
    log "ERROR: $mensaje"
    corta "autovolcado: $mensaje (el vigía backend-sync lo reintentará igualmente)"
    rm -f "$TMP"
    escribir_estado 6 "$mensaje" "$INICIO" "$(date -Is)"
    exit 6
  fi
  log "escaneo aplicado: $(cat "$TMP")"
  rm -f "$TMP"
fi

log "OK: volcado refrescado$( [[ "$HACER_SYNC" == "1" && "$DRY_RUN" != "1" ]] && echo ' y escaneo aplicado')"
escribir_estado 0 "ok" "$INICIO" "$(date -Is)"
exit 0


