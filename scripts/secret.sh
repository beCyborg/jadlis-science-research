#!/usr/bin/env bash
# secret.sh — единая точка чтения ключей ресерч-стека Jadlis (плагин search).
#
# Стандарт хранения: ключ вводится один раз и живёт в Связке ключей macOS (Keychain),
# не в файлах репозитория и не в shell-профиле. Два класса:
#   A — ключи MCP-серверов плагина (BRAVE_API_KEY, FIRECRAWL_API_KEY, REDDITAPIS_KEY,
#       YOUTUBE_API_KEY). Пишет их Claude Code при включении плагина (userConfig,
#       sensitive: true) в запись Keychain `Claude Code-credentials` → pluginSecrets.
#   B — ключи скриптов и curl-блоков протоколов (научные источники, Exa, YC, Places,
#       контактные почты). Пишет их скилл /search:keys как generic password:
#       service `jadlis`, account = имя ключа.
#
# ЗНАЧЕНИЯ КЛЮЧЕЙ НЕ ПЕЧАТАЮТСЯ НИГДЕ, КРОМЕ РЕЖИМОВ `KEY` И `--export`.

set -uo pipefail

SERVICE="jadlis"
SERVICE_LEGACY="jadlis-research"   # ключи, записанные до split 2026-09
PLUGIN_ID_PREFIX="search@"
PLUGIN_ID_DEFAULT="search@jadlis"

# Известные ключи для --list.
KNOWN_KEYS_A="BRAVE_API_KEY FIRECRAWL_API_KEY REDDITAPIS_KEY YOUTUBE_API_KEY"
KNOWN_KEYS_B="PUBMED_API_KEY PUBMED_EMAIL SEMANTIC_SCHOLAR_API_KEY OPENALEX_API_KEY \
OPENALEX_MAILTO CROSSREF_MAILTO UNPAYWALL_EMAIL CORE_API_KEY SCITE_API_KEY \
CONSENSUS_API_KEY EXA_API_KEY YC_SEARCH_API_KEY GOOGLE_PLACES_API_KEY \
TAVILY_API_KEY SERPER_API_KEY WYKOP_API_KEY"

TAB=$(printf '\t')
SERVICES_CACHE=""

usage() {
  cat <<'USAGE'
secret.sh — чтение ключей ресерч-стека Jadlis из Связки ключей macOS.

Порядок разрешения (первый непустой побеждает):
  1. переменная окружения $KEY
  2. Keychain generic password: service `jadlis`, account KEY
  3. pluginSecrets из блоба `Claude Code-credentials` (затем `Claude Code-credentials-*`)
  4. <config-dir>/.credentials.json → .pluginSecrets["search@<marketplace>"][KEY]
  5. <config-dir>/settings.json → .env[KEY]   (legacy-рельса)
Ничего не нашли → exit 1 и пустой stdout.

Режимы:
  secret.sh KEY                 значение на stdout (или exit 1 молча)
  secret.sh --export K1 K2 …    строки `export K=…` только для найденных, для eval
  secret.sh --which KEY         какой источник сработал (без значения)
  secret.sh --set KEY           значение читается со stdin и пишется в Keychain
  secret.sh --list              имена, длины и источники по известному списку ключей

Пример прелюда в Bash-блоке протокола:
  eval "$(bash "$PLUGIN_ROOT/scripts/secret.sh" --export PUBMED_API_KEY PUBMED_EMAIL)"
USAGE
}

err() { printf '%s\n' "$*" >&2; }
have_jq() { command -v jq >/dev/null 2>&1; }
have_security() { command -v security >/dev/null 2>&1; }

# Каталоги конфигурации Claude Code: активный профиль, затем дефолтный.
config_dirs() {
  local d seen=""
  for d in "${CLAUDE_CONFIG_DIR:-}" "$HOME/.claude"; do
    [ -n "$d" ] || continue
    case ":$seen:" in *":$d:"*) continue ;; esac
    seen="$seen:$d"
    printf '%s\n' "$d"
  done
}

# Имена служб Keychain с блобом креденшелов Claude Code. Значений не печатает:
# `security dump-keychain` без -d отдаёт только метаданные записей.
credential_services() {
  if [ -z "$SERVICES_CACHE" ]; then
    SERVICES_CACHE=$(
      printf '%s\n' "Claude Code-credentials"
      security dump-keychain 2>/dev/null \
        | sed -n 's/.*"svce"<blob>="\(Claude Code-credentials[^"]*\)".*/\1/p' \
        | sort -u \
        | grep -v '^Claude Code-credentials$'
    )
  fi
  printf '%s\n' "$SERVICES_CACHE"
}

# jq-выражение: достать $k из pluginSecrets — сперва по каноническому id
# `search@jadlis`, затем по любому `search@<marketplace>`.
PLUGIN_SECRET_JQ='
(.pluginSecrets // {}) as $ps
| ( $ps[$id][$k]?
    // ( $ps | to_entries
             | map(select(.key | startswith($prefix)))
             | map(.value[$k]?)
             | map(select(. != null and . != ""))
             | first )
    // empty )'

# resolve KEY → «источник<TAB>значение» на stdout, exit 1 если не найдено.
resolve() {
  local key="$1" v d f svc blob

  v="${!key-}"
  if [ -n "$v" ]; then printf '%s%s%s' "env" "$TAB" "$v"; return 0; fi

  if have_security; then
    for svc in "$SERVICE" "$SERVICE_LEGACY"; do
      v=$(security find-generic-password -s "$svc" -a "$key" -w 2>/dev/null)
      if [ -n "${v:-}" ]; then
        printf '%s%s%s' "keychain generic ($svc/$key)" "$TAB" "$v"; return 0
      fi
    done
  fi

  if have_security && have_jq; then
    while IFS= read -r svc; do
      [ -n "$svc" ] || continue
      blob=$(security find-generic-password -s "$svc" -w 2>/dev/null) || continue
      [ -n "$blob" ] || continue
      v=$(printf '%s' "$blob" | jq -r --arg k "$key" --arg id "$PLUGIN_ID_DEFAULT" \
            --arg prefix "$PLUGIN_ID_PREFIX" "$PLUGIN_SECRET_JQ" 2>/dev/null)
      if [ -n "${v:-}" ]; then
        printf '%s%s%s' "pluginSecrets ($svc)" "$TAB" "$v"; return 0
      fi
    done <<EOF
$(credential_services)
EOF
  fi

  if have_jq; then
    while IFS= read -r d; do
      f="$d/.credentials.json"
      [ -r "$f" ] || continue
      v=$(jq -r --arg k "$key" --arg id "$PLUGIN_ID_DEFAULT" --arg prefix "$PLUGIN_ID_PREFIX" \
            "$PLUGIN_SECRET_JQ" "$f" 2>/dev/null)
      if [ -n "${v:-}" ]; then
        printf '%s%s%s' "credentials.json ($f)" "$TAB" "$v"; return 0
      fi
    done <<EOF
$(config_dirs)
EOF

    while IFS= read -r d; do
      f="$d/settings.json"
      [ -r "$f" ] || continue
      v=$(jq -r --arg k "$key" '(.env // {})[$k] // empty' "$f" 2>/dev/null)
      if [ -n "${v:-}" ]; then
        printf '%s%s%s' "settings.json env ($f)" "$TAB" "$v"; return 0
      fi
    done <<EOF
$(config_dirs)
EOF
  fi

  return 1
}

value_of()  { printf '%s' "${1#*$TAB}"; }
source_of() { printf '%s' "${1%%$TAB*}"; }

mode_get() {
  local hit
  hit=$(resolve "$1") || return 1
  printf '%s\n' "$(value_of "$hit")"
}

mode_export() {
  local key hit found=0
  for key in "$@"; do
    hit=$(resolve "$key") || continue
    printf 'export %s=%q\n' "$key" "$(value_of "$hit")"
    found=1
  done
  [ "$found" = 1 ] || return 1
}

mode_which() {
  local hit
  hit=$(resolve "$1") || { printf '%s: не найден\n' "$1"; return 1; }
  printf '%s: %s\n' "$1" "$(source_of "$hit")"
}

mode_set() {
  local key="$1" value
  have_security || { err "secret.sh --set: нет утилиты security (не macOS)"; return 2; }
  IFS= read -r value || true
  if [ -z "${value:-}" ]; then
    err "secret.sh --set $key: пустое значение на stdin — ничего не записано"
    return 2
  fi
  if security add-generic-password -U -s "$SERVICE" -a "$key" -T /usr/bin/security \
       -w "$value" >/dev/null 2>&1; then
    printf 'OK: %s записан в Keychain (длина %s)\n' "$key" "${#value}"
  else
    err "FAIL: $key не записан (security add-generic-password вернул ошибку)"
    return 1
  fi
}

list_group() {
  local title="$1" keys="$2" key hit v
  printf '\n%s\n' "$title"
  for key in $keys; do
    if hit=$(resolve "$key"); then
      v=$(value_of "$hit")
      printf '  %-26s %-6s %s\n' "$key" "${#v}" "$(source_of "$hit")"
    else
      printf '  %-26s %-6s %s\n' "$key" "-" "НЕТ"
    fi
  done
}

mode_list() {
  printf '  %-26s %-6s %s\n' "КЛЮЧ" "ДЛИНА" "ИСТОЧНИК"
  list_group "— класс A: MCP-серверы плагина (спрашивает Claude Code) —" "$KNOWN_KEYS_A"
  list_group "— класс B: скрипты и curl-блоки (пишет /search:keys) —" "$KNOWN_KEYS_B"
}

main() {
  [ $# -ge 1 ] || { usage >&2; exit 2; }
  case "$1" in
    --export)  shift; [ $# -ge 1 ] || exit 1; mode_export "$@" ;;
    --which)   shift; [ $# -eq 1 ] || { usage >&2; exit 2; }; mode_which "$1" ;;
    --set)     shift; [ $# -eq 1 ] || { usage >&2; exit 2; }; mode_set "$1" ;;
    --list)    mode_list ;;
    -h|--help) usage ;;
    -*)        usage >&2; exit 2 ;;
    *)         [ $# -eq 1 ] || { usage >&2; exit 2; }; mode_get "$1" ;;
  esac
}

main "$@"
