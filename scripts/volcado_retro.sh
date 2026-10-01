#!/usr/bin/env bash
# =============================================================================
# volcado_retro.sh — Refresco AUTOMÁTICO del volcado de ROMs RETRO + escaneo.
#
# POR QUÉ EXISTE:
#   La colección retro (arcade, consolas, micros) vive en OTRO in-share de MEGA,
#   montado por OTRA cuenta del pool (el caso real: `INSHARE …:ORTIK 90`). No
#   comparte nada con la biblioteca de Switch (ni share, ni BD, ni página), pero
#   sí comparte el host: hay UNA sola sesión MEGAcmd. Este script cierra ese
#   hueco: rota a la cuenta que ve las ROMs, refresca SU volcado, restaura
#   SIEMPRE la sesión preferida de Switch y pide el escaneo de SU BD.
#
# QUÉ HACE:
#   1. Comprueba MEGAcmd y carga las credenciales retro (`ALUCARD_MEGA_ENV`).
#   2. Rota la sesión a la cuenta que ve la colección retro: pre-vuelo guiado por
#      el in-share de las ROMs con failover del pool (`verificar_rotacion.py
#      --elegir-cuenta`). Nunca se elige "a ciegas": se exige ver el share.
#   3. Refresca `mega_retro_contenido_MEGAcmd.txt` (escritura en sitio, mismo
#      inodo, guard anti-vaciado/anti-truncado y diff previo).
#   4. RESTAURA la sesión de la credencial preferida (Switch) — pase lo que pase
#      (trap EXIT) — para no dejar el pipeline principal apuntando al share de
#      ROMs.
#   5. Pide el escaneo a la API (`POST /api/retro/dump`): diff sobre SU BD
#      (`data/retro.db`). El worker `backend-retro-sync` es la red de seguridad.
#   6. Registra resultado en `data/volcado_retro.log` y `volcado_retro_estado.json`.
#
# USO:
#   ./scripts/volcado_retro.sh                 # refresco + escaneo
#   ./scripts/volcado_retro.sh --set-cred      # guarda la cuenta de las ROMs
#   ./scripts/volcado_retro.sh --dry-run       # no escribe el volcado
#   ./scripts/volcado_retro.sh --no-sync       # solo el volcado
#   ./scripts/volcado_retro.sh --install-cron  # cron cada 6 h (desfasado)
#   ./scripts/volcado_retro.sh --remove-cron   # quita la entrada de cron
#   ./scripts/volcado_retro.sh --estado        # último resultado + logs
#
# VARIABLES:
#   MEGA_BIN              binarios MEGAcmd (def. /home/christian/opt/megacmd/usr/bin)
#   ALUCARD_RETRO_ENV     credenciales de la cuenta de las ROMs
#                         (def. ~/.config/alucard/mega_retro.env; chmod 600)
#   ALUCARD_RETRO_OUT     volcado de salida (def. <repo>/data/mega_retro_contenido_MEGAcmd.txt)
#   ALUCARD_MEGA_CUENTAS  pool de cuentas para el failover (def. del helper)
#   ALUCARD_API_URL       API del backend (def. http://127.0.0.1:<BACKEND_PORT|7331>)
#   ALUCARD_PY            intérprete con las deps del backend (def. backend/.venv/bin/python)
#   ALUCARD_RETRO_CRON_HORAS  cadencia del cron instalado (def. 6)
#   ALUCARD_RETRO_PREFLIGHT   "0" desactiva el pre-vuelo (def. activado)
#   ALUCARD_RETRO_ROTACION    "0" desactiva el failover del pool (def. activado)
#   ALUCARD_RETRO_ROTACION_PERSISTIR  "1" persiste la cuenta elegida en ALUCARD_RETRO_ENV
#
# CÓDIGOS DE SALIDA: 0 ok · 4 sin sesión MEGA/credenciales · 5 fallo del volcado ·
#                    6 fallo del escaneo en la API · 7 otra ejecución en curso ·
#                    8 ninguna cuenta del pool ve la colección retro ·
#                    9 el volcado se aplicó pero la sesión MEGAcmd no volvió a Switch
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/mega_session.sh
source "$ROOT/scripts/lib/mega_session.sh"
MEGA_BIN="${MEGA_BIN:-/home/christian/opt/megacmd/usr/bin}"
ALUCARD_PY="${ALUCARD_PY:-$ROOT/backend/.venv/bin/python}"
# Credenciales de la cuenta de las ROMs: fichero PROPIO, fuera del repo. Al
# exportar ALUCARD_MEGA_ENV, `cargar_credenciales_mega` y `asegurar_sesion_mega`
# trabajan contra esa cuenta (y el pool sigue siendo el común para el failover).
RETRO_ENV="${ALUCARD_RETRO_ENV:-$HOME/.config/alucard/mega_retro.env}"
ALUCARD_MEGA_ENV="$RETRO_ENV"
export ALUCARD_MEGA_ENV
RETRO_OUT="${ALUCARD_RETRO_OUT:-$ROOT/data/mega_retro_contenido_MEGAcmd.txt}"
LOG_DIR="$ROOT/data"
LOG="$LOG_DIR/volcado_retro.log"
ESTADO="$LOG_DIR/volcado_retro_estado.json"
ESTADO_CUENTAS="$LOG_DIR/estado_cuentas_retro.json"
CRON_TAG="# alucard-retro (gestionado por scripts/volcado_retro.sh)"
CRON_HORAS="${ALUCARD_RETRO_CRON_HORAS:-6}"
# Desfasado 30 min del cron de Switch (17 */6): no compiten por la sesión MEGAcmd.
CRON_LINEA="47 */${CRON_HORAS} * * * $ROOT/scripts/volcado_retro.sh --quiet >> $LOG_DIR/volcado_retro-cron.log 2>&1 $CRON_TAG"

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
  log "cron retro instalado (cada ${CRON_HORAS} h): $(crontab -l | grep -F "$CRON_TAG")"
}

quitar_cron() {
  local actual
  actual="$(crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true)"
  printf '%s\n' "$actual" | crontab -
  log "cron retro retirado (el cron de Switch queda intacto)"
}

mostrar_estado() {
  if [[ -f "$ESTADO" ]]; then cat "$ESTADO"; else echo "(sin estado: aún no se ha ejecutado)"; fi
  echo "── pre-vuelo de rotación retro ($ESTADO_CUENTAS) ──"
  if [[ -f "$ESTADO_CUENTAS" ]]; then
    cat "$ESTADO_CUENTAS"
  else
    echo "(sin datos: aún no se ha ejecutado el pre-vuelo retro)"
  fi
  echo "── últimas 15 líneas de $LOG ──"
  if [[ -f "$LOG" ]]; then tail -n 15 "$LOG"; else echo "(sin log)"; fi
  echo "── crontab (retro) ──"
  crontab -l 2>/dev/null | grep -F "$CRON_TAG" || echo "(sin entrada de cron)"
}

restaurar_sesion_switch() {
  # Devuelve el host a una sesión de SWITCH tras el volcado de ROMs (la sesión
  # MEGAcmd es única). Dos intentos, en este orden:
  #   1. La credencial PREFERIDA de Switch (`ALUCARD_SWITCH_ENV` o `mega.env`): la
  #      normal. Se pasa EXPLÍCITAMENTE a los helpers (ver más abajo).
  #   2. Si su login falla (pasa: las cuentas rotan y una se queda caducada), el
  #      failover del pool GUIADO POR EL VOLCADO CANÓNICO de Switch: deja la
  #      sesión en la primera cuenta que ve la biblioteca, igual que `make rotacion`.
  # Comprueba el resultado de verdad: no basta con "haberlo intentado". Devuelve
  # 0 solo si la sesión activa vuelve a ser una cuenta de Switch.
  local preferida actual switch_env="${ALUCARD_SWITCH_ENV:-$MEGA_ENV_POR_DEFECTO}"
  preferida="$(mega_env_valor "$switch_env" MEGA_EMAIL)"
  actual="$(cuenta_activa_mega)"
  if [[ -n "$preferida" && "${actual,,}" == "${preferida,,}" ]]; then
    log "sesión ya en la credencial preferida ($actual)"
    return 0
  fi
  # OJO: este script exporta ALUCARD_MEGA_ENV=$RETRO_ENV (lo necesita el pre-vuelo
  # retro), y el helper de restauración leería ESE fichero (que puede no existir):
  # se le pasa explícitamente el fichero de SWITCH o no intentaría el login.
  (cd "$ROOT" && ALUCARD_MEGA_ENV="$switch_env" "$ALUCARD_PY" - "$MEGA_BIN" <<'PY'
import pathlib
import sys

sys.path.insert(0, "scripts")
import explorar_cuentas_mega as ex

ex.restaurar_preferida(pathlib.Path(sys.argv[1]).expanduser())
PY
  ) >>"$LOG" 2>&1 || log "AVISO: la restauración de la credencial preferida falló (detalle en $LOG)"
  actual="$(cuenta_activa_mega)"
  if [[ -n "$preferida" && "${actual,,}" == "${preferida,,}" ]]; then
    log "sesión restaurada a la credencial preferida ($actual)"
    return 0
  fi
  log "AVISO: la sesión no quedó en la credencial preferida (${preferida:-<sin definir>}; ahora: ${actual:-<ninguna>}); failover del pool para volver a Switch"
  local switch_dump="${ALUCARD_VOLCADO:-$ROOT/mega_cuenta_contenido_MEGAcmd.txt}"
  local pool="${MEGA_CUENTAS_FICHERO:-$MEGA_CUENTAS_POR_DEFECTO}"
  if [[ -f "$switch_dump" && -f "$pool" && "${ALUCARD_ROTACION:-1}" != "0" ]]; then
    local elegir=(--volcado "$switch_dump" --elegir-cuenta --cuentas "$pool"
                  --mega-bin "$MEGA_BIN" --json "$LOG_DIR/estado_cuentas.json" --quiet)
    [[ "${ALUCARD_ROTACION_PERSISTIR:-0}" == "1" ]] && elegir+=(--guardar-elegida)
    # También aquí el fichero de credenciales preferidas es el de SWITCH (mismo
    # motivo): es el que `verificar_rotacion.py` restaura si nadie ve la biblioteca.
    if ALUCARD_MEGA_ENV="$switch_env" "$ALUCARD_PY" "$ROOT/scripts/verificar_rotacion.py" \
        "${elegir[@]}" >>"$LOG" 2>&1; then
      log "sesión devuelta a Switch con la cuenta del pool $(cuenta_activa_mega)"
      return 0
    fi
    log "ERROR: ninguna cuenta del pool ve la biblioteca de Switch; el pre-vuelo de Switch lo reportará"
  else
    log "AVISO: sin volcado canónico de Switch ($switch_dump) o sin pool ($pool): no hay failover de vuelta"
  fi
  actual="$(cuenta_activa_mega)"
  if [[ -n "$CUENTA_ROMS" && -n "$actual" && "$actual" != "$CUENTA_ROMS" ]]; then
    log "sesión de vuelta en $actual (no es la cuenta de ROMs)"
    return 0
  fi
  # 3) Último recurso: retomar EXACTAMENTE la sesión que había antes de rotar (su
  #    clave se guardó al empezar). Así el host nunca queda peor de como estaba.
  if [[ -n "$SESION_PREVIA_CLAVE" && "$SESION_PREVIA_CUENTA" != "$CUENTA_ROMS" ]]; then
    log "retomando la sesión previa al volcado ($SESION_PREVIA_CUENTA)"
    if timeout 180 mega-login "$SESION_PREVIA_CLAVE" >/dev/null 2>&1; then
      mega_esperar_cuenta - "$MEGA_ESPERA_LOGIN" || true
      actual="$(cuenta_activa_mega)"
      if [[ -n "$actual" && "$actual" != "$CUENTA_ROMS" ]]; then
        log "sesión retomada tal cual estaba: $actual"
        return 0
      fi
    fi
    log "AVISO: no pude retomar la sesión previa ($SESION_PREVIA_CUENTA)"
  fi
  actual="$(cuenta_activa_mega)"
  corta "volcado_retro: la sesión quedó en ${actual:-<ninguna>} y NO pude devolverla a Switch (credencial preferida: ${preferida:-sin definir})"
  return 1
}

case "$ACCION" in
  install) instalar_cron; exit 0 ;;
  remove) quitar_cron; exit 0 ;;
  estado) mostrar_estado; exit 0 ;;
  set-cred)
    read -r -p 'MEGA_EMAIL (cuenta que ve las ROMs retro): ' _email
    read -r -s -p 'MEGA_PASSWORD: ' _pass
    echo
    guardar_credenciales_mega "$ROOT" "$_email" "$_pass"
    unset _pass
    exit 0
    ;;
esac

# ── Run: refresco del volcado retro + escaneo de SU BD ───────────────────────
INICIO="$(date -Is)"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOG_DIR/.volcado_retro.lock"
  if ! flock -n 9; then
    log "AVISO: ya hay un refresco retro en curso (lock ocupado); nada que hacer"
    escribir_estado 7 "ya hay un refresco retro en curso" "$INICIO" "$(date -Is)"
    exit 7
  fi
fi

export PATH="$MEGA_BIN:$PATH"

if ! command -v mega-whoami >/dev/null 2>&1; then
  mensaje="no encuentro MEGAcmd en $MEGA_BIN; revisa MEGA_BIN"
  log "ERROR: $mensaje"
  corta "volcado_retro: $mensaje"
  escribir_estado 4 "$mensaje" "$INICIO" "$(date -Is)"
  exit 4
fi

# La sesión MEGAcmd es ÚNICA en el host: la usará la cuenta de las ROMs mientras
# dure el volcado y, al final (trap EXIT), se devuelve a la preferida de Switch.
SESION_RESTAURADA=0
SESION_SWITCH_OK=1
# Cuenta usada para el volcado de ROMs (se fija justo antes de volcar): es la
# sesión a la que NO queremos volver al terminar.
CUENTA_ROMS=""
finalizar() {
  # Red de seguridad: si el script muere a medias (error, timeout, Ctrl+C) con la
  # sesión en la cuenta de las ROMs, se devuelve a Switch. Si tampoco se puede, NO
  # se calla: rc=9 y aviso por stderr (cron manda correo) además del log.
  local rc=$?
  if [[ "$SESION_RESTAURADA" != "1" ]]; then
    SESION_RESTAURADA=1
    restaurar_sesion_switch || SESION_SWITCH_OK=0
  fi
  if [[ "$SESION_SWITCH_OK" == "0" ]]; then
    [[ "$rc" == "0" ]] && rc=9
    escribir_estado "$rc" "la sesión MEGAcmd no volvió a Switch" \
      "${INICIO:-$(date -Is)}" "$(date -Is)"
  fi
  exit "$rc"
}
trap finalizar EXIT

# Clave de la sesión ACTUAL antes de tocar nada: el volcado de ROMs puede necesitar
# rotar de cuenta (la sesión MEGAcmd es única) y, si ningún login funciona, esta
# clave permite RETOMAR exactamente la sesión que había (nadie se queda peor).
SESION_PREVIA_CUENTA="$(cuenta_activa_mega)"
SESION_PREVIA_CLAVE=""
if [[ -n "$SESION_PREVIA_CUENTA" ]]; then
  SESION_PREVIA_CLAVE="$(timeout 60 mega-session 2>/dev/null | sed -n 's/.*session is:[[:space:]]*//p' | head -1)"
  log "sesión inicial: $SESION_PREVIA_CUENTA (clave guardada para poder retomarla)"
fi

# ¿Qué cuenta debe estar activa para volcar las ROMs? La responde la COLECCIÓN, no
# el login: `--elegir-cuenta` mide la sesión actual contra el in-share de ROMs y,
# solo si no lo ve, prueba el pool. Si la sesión actual YA vale, no toca nada (no
# hay logins innecesarios: la sesión MEGAcmd es única y cada rotación es un riesgo).
POOL="${MEGA_CUENTAS_FICHERO:-$MEGA_CUENTAS_POR_DEFECTO}"
if [[ -f "$RETRO_OUT" && "${ALUCARD_RETRO_PREFLIGHT:-1}" != "0" ]]; then
  if [[ "${ALUCARD_RETRO_ROTACION:-1}" == "0" ]]; then
    # Failover desactivado: solo se comprueba la sesión actual (diagnóstico).
    ELEGIR=(--volcado "$RETRO_OUT" --mega-bin "$MEGA_BIN" --json "$ESTADO_CUENTAS")
  else
    ELEGIR=(--volcado "$RETRO_OUT" --elegir-cuenta --cuentas "$POOL"
            --mega-bin "$MEGA_BIN" --json "$ESTADO_CUENTAS")
  fi
  if [[ "${ALUCARD_RETRO_ROTACION_PERSISTIR:-0}" == "1" ]]; then
    ELEGIR+=(--guardar-elegida --env-destino "$RETRO_ENV")
  fi
  [[ "$QUIET" == "1" ]] && ELEGIR+=(--quiet)
  if "$ALUCARD_PY" "$ROOT/scripts/verificar_rotacion.py" "${ELEGIR[@]}" >>"$LOG" 2>&1; then
    log "colección de ROMs alcanzable con la sesión $(cuenta_activa_mega) (failover por pool si hizo falta)"
  else
    rc=$?
    [[ "$rc" == "4" ]] || rc=8
    mensaje="pre-vuelo retro (rc=$rc): ni la sesión actual ni el pool ($POOL) ven la colección de ROMs; mira $ESTADO_CUENTAS"
    if [[ "$DRY_RUN" == "1" ]]; then
      log "AVISO: $mensaje (dry-run: se continúa sin escribir el volcado)"
    else
      log "ERROR: $mensaje"
      corta "volcado_retro: $mensaje → el volcado retro y su BD NO se tocan"
      escribir_estado "$rc" "$mensaje" "$INICIO" "$(date -Is)"
      exit "$rc"
    fi
  fi
elif [[ -z "$(cuenta_activa_mega)" ]]; then
  # Primer arranque SIN volcado previo: no hay biblioteca que verificar, así que
  # se entra con la credencial de las ROMs (`ALUCARD_MEGA_ENV` → mega_retro.env).
  if cargar_credenciales_mega "$ROOT"; then
    log "credenciales retro disponibles en $MEGA_EMAIL_FUENTE para $MEGA_EMAIL"
  else
    log "AVISO: sin credenciales retro ($RETRO_ENV): usa --set-cred"
  fi
  if ! asegurar_sesion_mega; then
    mensaje="sin sesión MEGAcmd utilizable y sin volcado retro previo (${MEGA_EMAIL:-sin credencial}); usa --set-cred"
    corta "volcado_retro: $mensaje"
    escribir_estado 4 "$mensaje" "$INICIO" "$(date -Is)"
    exit 4
  fi
  log "AVISO: sin volcado retro previo ($RETRO_OUT): se volcará lo que monte $(cuenta_activa_mega)"
fi

ARGS=(--out "$RETRO_OUT" --mega-bin "$MEGA_BIN")
[[ "$DRY_RUN" == "1" ]] && ARGS+=(--dry-run)
CUENTA_ROMS="$(cuenta_activa_mega)"
log "volcando ROMs con la sesión ${CUENTA_ROMS:-<ninguna>}: $ALUCARD_PY scripts/refrescar_volcado.py ${ARGS[*]}"
if ! "$ALUCARD_PY" "$ROOT/scripts/refrescar_volcado.py" "${ARGS[@]}" >>"$LOG" 2>&1; then
  rc=$?
  mensaje="el refresco del volcado retro falló (rc=$rc); mira $LOG"
  log "ERROR: $mensaje"
  corta "volcado_retro: $mensaje"
  escribir_estado 5 "$mensaje" "$INICIO" "$(date -Is)"
  exit 5
fi

# La sesión vuelve YA a Switch (el escaneo no necesita MEGAcmd): primero la
# credencial preferida y, si está caducada, el failover del pool guiado por el
# volcado canónico de Switch. Marcamos el intento para que el trap no lo repita.
restaurar_sesion_switch || SESION_SWITCH_OK=0
SESION_RESTAURADA=1

if [[ "$HACER_SYNC" == "1" && "$DRY_RUN" != "1" ]]; then
  URL="$(api_url)"
  TMP="$(mktemp)"
  codigo="$(curl -sS -o "$TMP" -w '%{http_code}' --max-time 1800 \
            -X POST "$URL/api/retro/dump" -H 'Content-Type: application/json' -d '{}' || echo 000)"
  if [[ "$codigo" != "200" ]]; then
    mensaje="el escaneo retro en la API falló (HTTP $codigo en $URL/api/retro/dump): $(head -c 400 "$TMP")"
    log "ERROR: $mensaje"
    corta "volcado_retro: $mensaje (el worker backend-retro-sync lo reintentará igualmente)"
    rm -f "$TMP"
    escribir_estado 6 "$mensaje" "$INICIO" "$(date -Is)"
    exit 6
  fi
  log "escaneo retro aplicado: $(cat "$TMP")"
  rm -f "$TMP"
fi

if [[ "$SESION_SWITCH_OK" == "0" ]]; then
  mensaje="el volcado retro y su BD se aplicaron, pero la sesión MEGAcmd NO volvió a Switch"
  log "ERROR: $mensaje"
  corta "volcado_retro: $mensaje"
  escribir_estado 9 "$mensaje" "$INICIO" "$(date -Is)"
  exit 9
fi

log "OK: volcado retro refrescado$( [[ "$HACER_SYNC" == "1" && "$DRY_RUN" != "1" ]] && echo ' y escaneo aplicado')"
escribir_estado 0 "ok" "$INICIO" "$(date -Is)"
exit 0

