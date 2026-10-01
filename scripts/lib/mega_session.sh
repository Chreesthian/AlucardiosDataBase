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
#
# FAILOVER ENTRE CUENTAS DEL POOL:
#   Las cuentas rotan cada semana y a veces una se queda con la contraseña
#   caducada. Si el login con la cuenta preferida falla, se prueban (en orden) las
#   cuentas de `$ALUCARD_MEGA_CUENTAS` (def.
#   ~/.config/alucard/mega_cuentas.txt, formato `email<sep>password`) y se sigue
#   con la primera que entre. Nunca se elige "a ciegas": `verificar_rotacion.py`
#   aborta después si esa cuenta no monta la biblioteca del volcado, así que un
#   failover a un share equivocado no puede vaciar la BD.
# =============================================================================

MEGA_ENV_POR_DEFECTO="${HOME:-/home/christian}/.config/alucard/mega.env"
MEGA_CUENTAS_POR_DEFECTO="${ALUCARD_MEGA_CUENTAS:-${HOME:-/home/christian}/.config/alucard/mega_cuentas.txt}"
MEGA_CUENTAS_FICHERO=""
MEGA_LOGIN_DETALLE=""
# Esperas acotadas a que MEGAcmd asiente la sesión (su rc y su salida llegan
# antes que `mega-whoami`; medido en el host: ~2-7 s por login).
MEGA_ESPERA_LOGIN="${MEGA_ESPERA_LOGIN:-90}"            # login con rc=0
MEGA_ESPERA_LOGIN_FALLO="${MEGA_ESPERA_LOGIN_FALLO:-15}" # login con rc!=0 (margen)
MEGA_ESPERA_LOGOUT="${MEGA_ESPERA_LOGOUT:-30}"           # cierre de la sesión previa

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
  local texto="$1" secreto
  # Se redactan también las contraseñas vistas en reintentos anteriores: el
  # failover prueba varias y ninguna debe acabar en un log.
  for secreto in "${MEGA_PASSWORD:-}" "${MEGA_PASSWORD_PREVIA:-}" "${MEGA_PASSWORD_INTENTO:-}"; do
    [[ -n "$secreto" ]] && texto="${texto//"$secreto"/***}"
  done
  printf '%s' "${texto%%$'\n'*}"
}

mega_cuentas_pool() {  # email<TAB>password por línea del fichero del pool (si existe)
  local fichero="${1:-$MEGA_CUENTAS_FICHERO}"
  local linea email pass
  # Separador: tabulador, ';', ',', '=' o espacios (mismo formato que
  # scripts/explorar_cuentas_mega.py). En variable para que bash no interprete
  # los metacaracteres del regex dentro de [[ ]].
  local credencial_re='^([^[:space:];=,]+)[[:space:];=,]+(.*)$'
  local comentario_re='^[[:space:]]*#'
  local -A vistos=()
  [[ -n "$fichero" && -f "$fichero" ]] || return 0
  while IFS= read -r linea || [[ -n "$linea" ]]; do
    linea="${linea%%$'\r'*}"
    [[ "$linea" =~ $comentario_re ]] && continue
    [[ -n "${linea//[[:space:]]/}" ]] || continue
    if [[ "$linea" =~ $credencial_re ]]; then
      email="${BASH_REMATCH[1]}"
      pass="${BASH_REMATCH[2]}"
    else
      continue  # sin contraseña: no es una credencial utilizable
    fi
    pass="${pass#"${pass%%[![:space:]]*}"}"  # ltrim
    pass="${pass%"${pass##*[![:space:]]}"}"  # rtrim
    [[ -n "$email" && -n "$pass" ]] || continue
    [[ -n "${vistos[${email,,}]:-}" ]] && continue
    vistos[${email,,}]=1
    printf '%s\t%s\n' "$email" "$pass"
  done <"$fichero"
}

mega_esperar_cuenta() {  # mega_esperar_cuenta <email|""|-> [segundos] → 0 si asienta
  # MEGAcmd contesta ANTES de que la sesión esté lista: tras `mega-login` su
  # `mega-whoami` puede seguir mostrando la cuenta anterior, y tras
  # `mega-logout --keep-session` el login siguiente falla con «Already logged in»
  # (rc=54). Sin esperar, un login CORRECTO se lee como fallido y el pipeline rota
  # de más: cada login es un riesgo (las credenciales rotan cada semana).
  #   <email>  → espera a que la sesión SEA esa cuenta
  #   ""       → espera a que NO haya sesión (cierre)
  #   "-"      → espera a que haya CUALQUIER sesión (def.)
  local email="${1--}" segundos="${2:-${MEGA_ESPERA_LOGIN:-90}}" i=0 cuenta
  while ((i < segundos)); do
    cuenta="$(cuenta_activa_mega)"
    if [[ "$email" == "-" ]]; then
      [[ -n "$cuenta" ]] && return 0
    else
      [[ "${cuenta,,}" == "${email,,}" ]] && return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  cuenta="$(cuenta_activa_mega)"
  if [[ "$email" == "-" ]]; then
    [[ -n "$cuenta" ]]
  else
    [[ "${cuenta,,}" == "${email,,}" ]]
  fi
}

mega_intentar_login() {  # mega_intentar_login <email> <password> → 0 si hay sesión
  local email="$1" pass="$2" salida rc=0 tmp espera
  MEGA_PASSWORD_INTENTO="$pass"
  # MEGAcmd mete bytes NUL en su salida (bash avisa al sustituirla y podría
  # truncar el diagnóstico): se limpia con `tr`, y el login se vuelca a un
  # temporal para que el rc registrado sea el de MEGAcmd y no el de `tr`.
  tmp="$(mktemp)"
  timeout 180 mega-login "$email" "$pass" >"$tmp" 2>&1 || rc=$?
  salida="$(tr -d '\000' <"$tmp")"
  rm -f "$tmp"
  # El rc de MEGAcmd no es fiable (devuelve 0 aunque la sesión no llegue a
  # montarse): se espera al asentamiento. Si el rc sí dijo fallo, la espera es
  # corta (margen por si mintió) para no alargar un failover real.
  espera="$MEGA_ESPERA_LOGIN"
  [[ "$rc" != "0" ]] && espera="$MEGA_ESPERA_LOGIN_FALLO"
  if mega_esperar_cuenta "$email" "$espera"; then
    MEGA_LOGIN_DETALLE="ok"
    return 0
  fi
  MEGA_LOGIN_DETALLE="rc=$rc $(mega_sanear "${salida:-sin salida}")"
  return 1
}

cuenta_activa_mega() {
  timeout 90 mega-whoami 2>/dev/null | sed -n 's/^Account e-mail:[[:space:]]*//p' | head -1
}

asegurar_sesion_mega() {  # 0 = sesión utilizable · 4 = sin sesión/con credenciales malas
  local cuenta actual previa candidato email pass
  local -a candidatos=()
  MEGA_CUENTAS_FICHERO="${MEGA_CUENTAS_FICHERO:-$MEGA_CUENTAS_POR_DEFECTO}"
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

  # Candidatos del pool (otras cuentas de la rotación) para el failover. Se
  # descarta la preferida porque ya se va a intentar primero.
  while IFS=$'\t' read -r email pass; do
    [[ -n "$email" && -n "$pass" ]] || continue
    [[ "${email,,}" == "${MEGA_EMAIL,,}" ]] && continue
    candidatos+=("$email"$'\t'"$pass")
  done < <(mega_cuentas_pool)

  # Rotación de la semana. MEGAcmd admite UNA sola sesión y rechaza el `login`
  # si ya hay otra activa ("Already logged in"): se cierra la actual
  # CONSERVÁNDOLA (--keep-session) para poder retomarla si las credenciales
  # nuevas no sirven, y así el host nunca se queda sin MEGAcmd.
  previa="$(timeout 60 mega-session 2>/dev/null | sed -n 's/.*session is:[[:space:]]*//p' | head -1)"
  log "rotación de credenciales: sesión=${cuenta:-<ninguna>} → cuenta=$MEGA_EMAIL (fuente: $MEGA_EMAIL_FUENTE)"
  if [[ -n "$cuenta" ]]; then
    if salida="$(timeout 120 mega-logout --keep-session 2>&1)"; then
      log "sesión anterior cerrada con --keep-session (retomable si hiciera falta)"
      # MEGAcmd rechaza un `mega-login` si todavía ve la sesión previa
      # («Already logged in», rc=54): se espera a que el cierre asiente.
      mega_esperar_cuenta "" "$MEGA_ESPERA_LOGOUT" ||
        log "AVISO: MEGAcmd tarda en cerrar la sesión anterior (sigo igualmente)"
    else
      log "AVISO: no pude cerrar la sesión anterior: $(mega_sanear "$salida")"
    fi
  fi
  unset salida

  if mega_intentar_login "$MEGA_EMAIL" "$MEGA_PASSWORD"; then
    log "sesión MEGAcmd activa: $MEGA_EMAIL (rotación aplicada)"
    return 0
  fi
  log "ERROR: no pude iniciar sesión con $MEGA_EMAIL ($MEGA_LOGIN_DETALLE)"

  # Failover: la credencial de la semana puede estar caducada (pasa de verdad).
  # Se prueba el resto del pool; el pre-vuelo decidirá después si esa cuenta ve
  # la biblioteca del volcado.
  if [[ ${#candidatos[@]} -gt 0 ]]; then
    log "failover: probando ${#candidatos[@]} cuenta(s) del pool ($MEGA_CUENTAS_FICHERO)"
    for candidato in "${candidatos[@]}"; do
      email="${candidato%%$'\t'*}"
      pass="${candidato#*$'\t'}"
      if mega_intentar_login "$email" "$pass"; then
        MEGA_PASSWORD_PREVIA="${MEGA_PASSWORD:-}"
        MEGA_EMAIL="$email"
        MEGA_PASSWORD="$pass"
        MEGA_EMAIL_FUENTE="pool:$MEGA_CUENTAS_FICHERO (failover)"
        log "failover de credenciales: sesión activa $email"
        return 0
      fi
      log "failover: $email tampoco entra ($MEGA_LOGIN_DETALLE)"
    done
  elif [[ -n "$MEGA_CUENTAS_FICHERO" && ! -f "$MEGA_CUENTAS_FICHERO" ]]; then
    log "AVISO: sin pool de cuentas ($MEGA_CUENTAS_FICHERO): no hay failover posible"
  fi

  actual="$(cuenta_activa_mega)"
  # Credenciales nuevas sin acceso: se retoma la sesión anterior para que el
  # pipeline siga pudiendo refrescar mientras se corrige la credencial.
  if [[ -n "$previa" && -z "$actual" ]]; then
    log "AVISO: el login falló y no hay sesión; retomando la anterior"
    timeout 180 mega-login "$previa" >/dev/null 2>&1 || true
    mega_esperar_cuenta - "$MEGA_ESPERA_LOGIN" || true
    actual="$(cuenta_activa_mega)"
  fi
  log "ERROR: sin sesión MEGAcmd utilizable para $MEGA_EMAIL ni para el pool"
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
