#!/usr/bin/env bash
# =============================================================================
# lib/mega_session.sh — Credenciales MEGA ROTATIVAS + sesión MEGAcmd.
#
# CONTEXTO:
#   Las credenciales de MEGA rotan semana a semana (cuentas distintas que montan
#   el MISMO share con la biblioteca). El pipeline no debe depender de qué cuenta
#   esté activa, pero sí debe poder re-loguearse solo y fallar RUIDOSO cuando las
#   credenciales nuevas no alcanzan los mismos datos.
#
# QUÉ OFRECE (se carga con `source`):
#   cargar_credenciales_mega <raíz>   → MEGA_EMAIL/MEGA_PASSWORD (del entorno o
#                                       de un fichero) sin imprimir jamás valores.
#   cuenta_activa_mega                → email de la sesión MEGAcmd activa (o "").
#   asegurar_sesion_mega              → rota la sesión si hace falta (login
#                                       primero, y si falla RESTAURA la previa);
#                                       devuelve 0 o 4 (sin sesión utilizable).
#   guardar_credenciales_mega <raíz>  → escribe las credenciales en el fichero
#                                       externo (chmod 600) para la rotación.
#
# ORDEN DE BÚSQUEDA DE CREDENCIALES (el primero que las defina gana):
#   1. entorno (MEGA_EMAIL/MEGA_PASSWORD)   2. $ALUCARD_MEGA_ENV
#   3. <raíz>/.env                          4. <raíz>/backend/.env
#   5. ~/.config/alucard/mega.env  (recomendado: fuera del repo, chmod 600)
# =============================================================================

MEGA_ENV_POR_DEFECTO="${HOME:-/home/christian}/.config/alucard/mega.env"

# `log` de respaldo si el script que carga el helper no define el suyo.
if ! declare -F log >/dev/null 2>&1; then
  log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
fi

mega_env_valor() {  # mega_env_valor <fichero> <CLAVE>
  [[ -f "$1" ]] || return 0
  sed -n "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*//p" "$1" | tail -1 |
    sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
}

mega_fuentes_credenciales() {  # mega_fuentes_credenciales <raíz>
  printf '%s\n' "${ALUCARD_MEGA_ENV:-}" "$1/.env" "$1/backend/.env" "$MEGA_ENV_POR_DEFECTO"
}

cargar_credenciales_mega() {  # cargar_credenciales_mega <raíz> → 0 si hay email
  local raiz="$1" fichero email pass
  MEGA_EMAIL_FUENTE="(entorno)"
  if [[ -z "${MEGA_EMAIL:-}" ]]; then
    MEGA_EMAIL_FUENTE=""
    while IFS= read -r fichero; do
      [[ -n "$fichero" && -f "$fichero" ]] || continue
      email="$(mega_env_valor "$fichero" MEGA_EMAIL)"
      [[ -n "$email" ]] || continue
      pass="$(mega_env_valor "$fichero" MEGA_PASSWORD)"
      MEGA_EMAIL="$email"
      MEGA_PASSWORD="$pass"
      MEGA_EMAIL_FUENTE="$fichero"
      break
    done <<<"$(mega_fuentes_credenciales "$raiz")"
  fi
  [[ -n "${MEGA_EMAIL:-}" ]]
}

mega_sanear() {  # mega_sanear <texto> — nunca dejar la contraseña en un log
  local texto="$1"
  if [[ -n "${MEGA_PASSWORD:-}" ]]; then
    texto="${texto//"$MEGA_PASSWORD"/***}"
  fi
  printf '%s' "${texto%%$'\n'*}"
}

cuenta_activa_mega() {
  timeout 90 mega-whoami 2>/dev/null | sed -n 's/^Account e-mail:[[:space:]]*//p' | head -1
}

asegurar_sesion_mega() {  # 0 = sesión utilizable · 4 = sin sesión/con credenciales malas
  local cuenta actual previa salida rc_login=0
  cuenta="$(cuenta_activa_mega)"

  if [[ -z "${MEGA_EMAIL:-}" ]]; then
    if [[ -n "$cuenta" ]]; then
      log "AVISO: sin MEGA_EMAIL/MEGA_PASSWORD; uso la sesión existente ($cuenta)"
      return 0
    fi
    log "ERROR: no hay sesión MEGAcmd ni credenciales MEGA_EMAIL/MEGA_PASSWORD"
    return 4
  fi

  if [[ "$cuenta" == "$MEGA_EMAIL" ]]; then
    log "sesión MEGAcmd vigente: $cuenta (credenciales: $MEGA_EMAIL_FUENTE)"
    return 0
  fi

  # Rotación de la semana. MEGAcmd admite UNA sola sesión y rechaza el `login`
  # si ya hay otra activa ("Already logged in"): se cierra la actual
  # CONSERVÁNDOLA (--keep-session) para poder retomarla si las credenciales
  # nuevas no sirven, y así el host nunca se queda sin MEGAcmd.
  previa="$(timeout 60 mega-session 2>/dev/null | sed -n 's/.*session is:[[:space:]]*//p' | head -1)"
  log "rotación de credenciales: sesión=${cuenta:-<ninguna>} → cuenta=$MEGA_EMAIL (fuente: $MEGA_EMAIL_FUENTE)"
  if [[ -n "$cuenta" ]]; then
    if salida="$(timeout 120 mega-logout --keep-session 2>&1)"; then
      log "sesión anterior cerrada con --keep-session (retomable si hiciera falta)"
    else
      log "AVISO: no pude cerrar la sesión anterior: $(mega_sanear "$salida")"
    fi
  fi

  if salida="$(timeout 180 mega-login "$MEGA_EMAIL" "$MEGA_PASSWORD" 2>&1)"; then
    rc_login=0
  else
    rc_login=$?
  fi
  actual="$(cuenta_activa_mega)"
  if [[ "$actual" == "$MEGA_EMAIL" ]]; then
    log "sesión MEGAcmd activa: $actual (rotación aplicada)"
    return 0
  fi

  # Credenciales nuevas sin acceso: se retoma la sesión anterior para que el
  # pipeline siga pudiendo refrescar mientras se corrige la credencial.
  if [[ -n "$previa" && -z "$actual" ]]; then
    log "AVISO: el login falló y no hay sesión; retomando la anterior"
    timeout 180 mega-login "$previa" >/dev/null 2>&1 || true
    actual="$(cuenta_activa_mega)"
  fi
  log "ERROR: no pude iniciar sesión con $MEGA_EMAIL (rc=$rc_login): $(mega_sanear "${salida:-sin salida}")"
  [[ -n "$actual" ]] && log "AVISO: se mantiene la sesión $actual (el volcado puede seguir usándola)"
  return 4
}

guardar_credenciales_mega() {  # guardar_credenciales_mega <raíz> <email> <password>
  local raiz="$1" email="$2" password="$3" destino="${ALUCARD_MEGA_ENV:-$MEGA_ENV_POR_DEFECTO}"
  mkdir -p "$(dirname "$destino")"
  umask 077
  printf 'MEGA_EMAIL=%s\nMEGA_PASSWORD=%s\n' "$email" "$password" >"$destino"
  chmod 600 "$destino"
  log "credenciales guardadas en $destino (chmod 600) para $email"
}
