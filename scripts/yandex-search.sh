#!/usr/bin/env bash
set -euo pipefail

# yandex-search.sh — Yandex Web Search (Рунет) via Yandex Cloud Search API v2 (sync + async).
# Host: searchapi.api.cloud.yandex.net — POST /v2/web/search (sync) | /v2/web/searchAsync (async)
# Poll: ${YC_OPERATION_HOST:-https://operation.api.cloud.yandex.net}/operations/<id>
#       404 on primary → auto-fallback to https://searchapi.api.cloud.yandex.net/v2/operations/<id>
# Auth: Api-Key in ENV YC_SEARCH_API_KEY (set it in `env` of settings.json — skill
#       /jadlis-research:keys walks you through it);
#       service account role search-api.webSearch.user, scope yc.search-api.execute.
#       folderId NOT required with Api-Key (derived from the key's service account;
#       verified live 2026-07-17). YC_FOLDER_ID / --folder-id to send it explicitly.
#
# PRICING (official, verified 2026-08-04; с НДС):
#   sync  0.488 ₽/req (night 00:00–07:59 MSK: 0.366) — single interactive checks ONLY
#   async 0.0305 ₽/req (night: 0.02541) — ×16 cheaper, hence the DEFAULT mode
#   Auth/server errors are not billed. Every billed submit prints a [cost] line to stderr
#   and appends a TSV row to <skill>/.usage.log (--no-log disables the file log).
#
# GOTCHAS:
#   - queryText ≤400 chars AND ≤40 words — enforced here BEFORE HTTP (API would 400).
#   - region is valid only for searchType ru|tr; dropped with [warn] otherwise
#     (use --json-patch to force it and observe the API error yourself).
#   - XML-only fields (sortSpec, groupSpec.groupMode/docsInGroup, maxPassages) are
#     stripped with [warn] when responseFormat=FORMAT_HTML arrives via --json-patch;
#     an HTML payload is emitted raw (parser is XML-only).
#   - async result is stored 12 h server-side; --no-wait prints operation_id=… for a
#     later --fetch. Quotas 10 rps (submit and poll); sleep ≥0.15 s between batch submits.
#   - stdout carries ONLY the result (or operation_id=…); all diagnostics go to stderr
#     ([cost], [poll], [warn], [error]) — stdout is safe to pipe.
#
# Exit codes: 0 ok (incl. found=0) | 1 usage | 2 no key | 3 API error | 4 poll timeout
#             (operation_id=… printed to stdout) | 5 response unparseable

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SKILL_DIR=$(dirname "$SCRIPT_DIR")
LOG_FILE="$SKILL_DIR/.usage.log"

API_HOST="https://searchapi.api.cloud.yandex.net"
OP_BASE_PRIMARY="${YC_OPERATION_HOST:-https://operation.api.cloud.yandex.net}/operations"
OP_BASE_FALLBACK="$API_HOST/v2/operations"

err() { printf '%s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
Usage:
  yandex-search.sh "<query>" [options]      # async by default: submit → poll → parse
  yandex-search.sh --fetch <operation-id>   # retrieve earlier async result (12 h window)

API options:
  --sync                sync call (0.488 ₽ vs 0.0305 ₽ async — single interactive checks only)
  -t, --type X          ru|com|tr|kk|be|uz (default ru)
  -r, --region N        region id, ru|tr only (default 225=РФ; 213=Москва, 2=СПб)
  -p, --page N          results page, 0-based (default 0)
  -n, --num N           groups per page 1..100 (default 20)
      --group-mode X    flat|deep (default flat)
      --docs-in-group N 1..3 (default 1; XML only)
      --passages N      max passages per doc 1..5 (XML only)
      --sort X          relevance|time
      --order X         desc|asc (meaningful with --sort time)
      --family X        moderate|none|strict
      --fix-typo X      on|off
      --folder-id ID    explicit folderId (default $YC_FOLDER_ID if set, else omitted)
      --json-patch JSON deep-merged into request body LAST — escape hatch for l10n,
                        userAgent, responseFormat, resultsWithin, future fields

Output options:
  --out X               text|json|urls (default text)
  --passage-chars N     truncate passages in text mode (default 220)
  --raw                 decoded XML (or HTML) payload as-is
  --raw-json            raw API envelope (sync response / operation JSON)

Behavior:
  --dry-run             print {endpoint, body} and exit — no HTTP, no key needed, 0 ₽
  --no-wait             async: submit, print operation_id=…, exit 0 (later: --fetch)
  --timeout SEC         polling budget (default 300)
  --interval SEC        fixed poll interval (default ladder 2→3→5 s)
  -v, --verbose         poll/debug detail on stderr
  --no-log              do not append to .usage.log
  -h, --help

Env:
  YC_SEARCH_API_KEY     Yandex Cloud Api-Key (role search-api.webSearch.user) — required
  YC_FOLDER_ID          optional; folderId is derived from the key if omitted
  YC_OPERATION_HOST     optional override of the operation-polling host
EOF
}

# ---------- parse arguments ----------
MODE=async
QUERY=""
OP_ID=""
TYPE=ru
REGION=225
REGION_EXPLICIT=0
PAGE=""
NUM=20
GROUP_MODE=flat
DOCS_IN_GROUP=1
PASSAGES=""
SORT=""
ORDER=""
FAMILY=""
FIX_TYPO=""
FOLDER_ID="${YC_FOLDER_ID:-}"
JSON_PATCH=""
OUT=text
PASSAGE_CHARS=220
RAW=0
RAW_JSON=0
DRY_RUN=0
NO_WAIT=0
TIMEOUT=300
INTERVAL=""
VERBOSE=0
NO_LOG=0

POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync)          MODE=sync ;;
    --fetch)         MODE=fetch; OP_ID="${2:?--fetch requires <operation-id>}"; shift ;;
    -t|--type)       TYPE="${2:?}"; shift ;;
    -r|--region)     REGION="${2:?}"; REGION_EXPLICIT=1; shift ;;
    -p|--page)       PAGE="${2:?}"; shift ;;
    -n|--num)        NUM="${2:?}"; shift ;;
    --group-mode)    GROUP_MODE="${2:?}"; shift ;;
    --docs-in-group) DOCS_IN_GROUP="${2:?}"; shift ;;
    --passages)      PASSAGES="${2:?}"; shift ;;
    --sort)          SORT="${2:?}"; shift ;;
    --order)         ORDER="${2:?}"; shift ;;
    --family)        FAMILY="${2:?}"; shift ;;
    --fix-typo)      FIX_TYPO="${2:?}"; shift ;;
    --folder-id)     FOLDER_ID="${2:?}"; shift ;;
    --json-patch)    JSON_PATCH="${2:?}"; shift ;;
    --out)           OUT="${2:?}"; shift ;;
    --passage-chars) PASSAGE_CHARS="${2:?}"; shift ;;
    --raw)           RAW=1 ;;
    --raw-json)      RAW_JSON=1 ;;
    --dry-run)       DRY_RUN=1 ;;
    --no-wait)       NO_WAIT=1 ;;
    --timeout)       TIMEOUT="${2:?}"; shift ;;
    --interval)      INTERVAL="${2:?}"; shift ;;
    -v|--verbose)    VERBOSE=1 ;;
    --no-log)        NO_LOG=1 ;;
    -h|--help)       usage; exit 0 ;;
    -*)              err "[error] unknown option: $1"; err "run with --help for usage"; exit 1 ;;
    *)               POSITIONAL+=("$1") ;;
  esac
  shift
done

if [[ "$MODE" == "fetch" ]]; then
  if [[ $DRY_RUN -eq 1 ]]; then err "[error] --dry-run is incompatible with --fetch"; exit 1; fi
  if [[ ${#POSITIONAL[@]} -gt 0 ]]; then err "[error] --fetch takes no query"; exit 1; fi
else
  QUERY="${POSITIONAL[0]:-}"
  if [[ -z "$QUERY" ]]; then err "[error] query is required"; err "run with --help for usage"; exit 1; fi
  if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
    err "[error] multiple positional args — quote the query: yandex-search.sh \"два слова\""; exit 1
  fi
fi

# ---------- validate & map enums ----------
case "$TYPE" in
  ru)  ST_ENUM="SEARCH_TYPE_RU" ;;
  com) ST_ENUM="SEARCH_TYPE_COM" ;;
  tr)  ST_ENUM="SEARCH_TYPE_TR" ;;
  kk)  ST_ENUM="SEARCH_TYPE_KK" ;;
  be)  ST_ENUM="SEARCH_TYPE_BE" ;;
  uz)  ST_ENUM="SEARCH_TYPE_UZ" ;;
  *) err "[error] --type must be ru|com|tr|kk|be|uz"; exit 1 ;;
esac
case "$GROUP_MODE" in
  flat) GM_ENUM="GROUP_MODE_FLAT" ;;
  deep) GM_ENUM="GROUP_MODE_DEEP" ;;
  *) err "[error] --group-mode must be flat|deep"; exit 1 ;;
esac
FAM_ENUM=""
if [[ -n "$FAMILY" ]]; then
  case "$FAMILY" in
    moderate) FAM_ENUM="FAMILY_MODE_MODERATE" ;;
    none)     FAM_ENUM="FAMILY_MODE_NONE" ;;
    strict)   FAM_ENUM="FAMILY_MODE_STRICT" ;;
    *) err "[error] --family must be moderate|none|strict"; exit 1 ;;
  esac
fi
FT_ENUM=""
if [[ -n "$FIX_TYPO" ]]; then
  case "$FIX_TYPO" in
    on)  FT_ENUM="FIX_TYPO_MODE_ON" ;;
    off) FT_ENUM="FIX_TYPO_MODE_OFF" ;;
    *) err "[error] --fix-typo must be on|off"; exit 1 ;;
  esac
fi
SORT_ENUM=""
if [[ -n "$SORT" ]]; then
  case "$SORT" in
    relevance) SORT_ENUM="SORT_MODE_BY_RELEVANCE" ;;
    time)      SORT_ENUM="SORT_MODE_BY_TIME" ;;
    *) err "[error] --sort must be relevance|time"; exit 1 ;;
  esac
fi
ORDER_ENUM=""
if [[ -n "$ORDER" ]]; then
  case "$ORDER" in
    desc) ORDER_ENUM="SORT_ORDER_DESC" ;;
    asc)  ORDER_ENUM="SORT_ORDER_ASC" ;;
    *) err "[error] --order must be desc|asc"; exit 1 ;;
  esac
fi
case "$OUT" in text|json|urls) ;; *) err "[error] --out must be text|json|urls"; exit 1 ;; esac

num_re='^[0-9]+$'
if ! [[ "$NUM" =~ $num_re ]] || (( NUM < 1 || NUM > 100 )); then
  err "[error] --num must be 1..100"; exit 1
fi
if ! [[ "$DOCS_IN_GROUP" =~ $num_re ]] || (( DOCS_IN_GROUP < 1 || DOCS_IN_GROUP > 3 )); then
  err "[error] --docs-in-group must be 1..3"; exit 1
fi
if [[ -n "$PASSAGES" ]] && { ! [[ "$PASSAGES" =~ $num_re ]] || (( PASSAGES < 1 || PASSAGES > 5 )); }; then
  err "[error] --passages must be 1..5"; exit 1
fi
if [[ -n "$PAGE" ]] && ! [[ "$PAGE" =~ $num_re ]]; then
  err "[error] --page must be a non-negative integer"; exit 1
fi
if ! [[ "$TIMEOUT" =~ $num_re ]]; then err "[error] --timeout must be integer seconds"; exit 1; fi
if [[ -n "$JSON_PATCH" ]] && ! jq -e . >/dev/null 2>&1 <<<"$JSON_PATCH"; then
  err "[error] --json-patch is not valid JSON"; exit 1
fi

# query length limits — checked BEFORE any HTTP (API 400s otherwise)
if [[ "$MODE" != "fetch" ]]; then
  qchars=$(printf '%s' "$QUERY" | wc -m | tr -d ' ')
  qwords=$(printf '%s' "$QUERY" | wc -w | tr -d ' ')
  if (( qchars > 400 )); then
    err "[error] query too long: ${qchars} chars (API limit 400)"; exit 1
  fi
  if (( qwords > 40 )); then
    err "[error] query too long: ${qwords} words (API limit 40)"; exit 1
  fi
fi

# ---------- build request body ----------
HTML_MODE=0
BODY=""
if [[ "$MODE" != "fetch" ]]; then
  q_json=$(jq -cn --arg st "$ST_ENUM" --arg qt "$QUERY" '{searchType:$st, queryText:$qt}')
  if [[ -n "$FAM_ENUM" ]]; then q_json=$(jq -c --arg v "$FAM_ENUM" '. + {familyMode:$v}' <<<"$q_json"); fi
  if [[ -n "$PAGE" ]];     then q_json=$(jq -c --arg v "$PAGE" '. + {page:$v}' <<<"$q_json"); fi
  if [[ -n "$FT_ENUM" ]];  then q_json=$(jq -c --arg v "$FT_ENUM" '. + {fixTypoMode:$v}' <<<"$q_json"); fi

  gs_json=$(jq -cn --arg gm "$GM_ENUM" --arg n "$NUM" --arg d "$DOCS_IN_GROUP" \
    '{groupMode:$gm, groupsOnPage:$n, docsInGroup:$d}')

  BODY=$(jq -cn --argjson q "$q_json" --argjson gs "$gs_json" '{query:$q, groupSpec:$gs}')

  if [[ -n "$SORT_ENUM" || -n "$ORDER_ENUM" ]]; then
    ss_json=$(jq -cn --arg sm "$SORT_ENUM" --arg so "$ORDER_ENUM" \
      '(if $sm != "" then {sortMode:$sm} else {} end) + (if $so != "" then {sortOrder:$so} else {} end)')
    BODY=$(jq -c --argjson v "$ss_json" '. + {sortSpec:$v}' <<<"$BODY")
  fi
  if [[ -n "$PASSAGES" ]]; then BODY=$(jq -c --arg v "$PASSAGES" '. + {maxPassages:$v}' <<<"$BODY"); fi

  # region: valid for ru|tr only (docs, verified 2026-08-04)
  if [[ "$TYPE" == "ru" || "$TYPE" == "tr" ]]; then
    BODY=$(jq -c --arg v "$REGION" '. + {region:$v}' <<<"$BODY")
  elif [[ $REGION_EXPLICIT -eq 1 ]]; then
    err "[warn] --region is only valid for --type ru|tr — dropped (force via --json-patch to see the API error)"
  fi

  if [[ -n "$FOLDER_ID" ]]; then BODY=$(jq -c --arg v "$FOLDER_ID" '. + {folderId:$v}' <<<"$BODY"); fi

  if [[ -n "$JSON_PATCH" ]]; then
    BODY=$(jq -cn --argjson a "$BODY" --argjson b "$JSON_PATCH" '$a * $b')
  fi

  fmt=$(jq -r '.responseFormat // ""' <<<"$BODY")
  if [[ "$fmt" == "FORMAT_HTML" ]]; then
    HTML_MODE=1
    stripped=$(jq -c 'del(.sortSpec, .maxPassages, .groupSpec.docsInGroup, .groupSpec.groupMode)' <<<"$BODY")
    if [[ "$stripped" != "$BODY" ]]; then
      err "[warn] FORMAT_HTML: XML-only fields (sortSpec/maxPassages/docsInGroup/groupMode) stripped from request"
      BODY="$stripped"
    fi
  fi
fi

if [[ "$MODE" == "sync" ]]; then
  ENDPOINT="$API_HOST/v2/web/search"
else
  ENDPOINT="$API_HOST/v2/web/searchAsync"
fi

if [[ $DRY_RUN -eq 1 ]]; then
  jq -n --arg e "$ENDPOINT" --argjson b "$BODY" '{endpoint:$e, body:$b}'
  exit 0
fi

# ---------- auth & pricing ----------
if [[ -z "${YC_SEARCH_API_KEY:-}" ]]; then
  err "[error] YC_SEARCH_API_KEY not set — add it to \"env\" in settings.json (Yandex Cloud Api-Key, role search-api.webSearch.user); skill /jadlis-research:keys"
  exit 2
fi
AUTH_HDR="Authorization: Api-Key ${YC_SEARCH_API_KEY}"

msk_hour=$(TZ=Europe/Moscow date +%H)
if (( 10#$msk_hour < 8 )); then
  COST_SYNC=0.366; COST_ASYNC=0.02541   # night discount 00:00–07:59 MSK
else
  COST_SYNC=0.488; COST_ASYNC=0.0305
fi

TMP=$(mktemp -d "${TMPDIR:-/tmp}/yxs.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
RESP_FILE="$TMP/resp.json"
OP_FILE="$TMP/op.json"
B64_FILE="$TMP/raw.b64"
PAYLOAD_FILE="$TMP/payload"

log_cost() { # $1 mode  $2 cost
  local q60="${QUERY:0:60}"
  err "[cost] $1 ~$2₽ | $q60"
  if [[ $NO_LOG -eq 0 ]]; then
    printf '%s\t%s\t%s\t%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$2" "$q60" >> "$LOG_FILE"
  fi
}

submit() { # POST $ENDPOINT with $BODY → $RESP_FILE; exits 3 on non-200
  local code
  if [[ $VERBOSE -eq 1 ]]; then err "[debug] POST $ENDPOINT"; err "[debug] body: $BODY"; fi
  code=$(curl -sS -o "$RESP_FILE" -w '%{http_code}' -X POST "$ENDPOINT" \
    -H "$AUTH_HDR" -H 'Content-Type: application/json' -d "$BODY") || {
    err "[error] curl failed (network) POST $ENDPOINT"; exit 3; }
  if [[ "$code" != "200" ]]; then
    err "[error] API HTTP $code:"
    cat "$RESP_FILE" >&2 || true
    err ""
    exit 3
  fi
}

poll_op() { # $1 operation-id → $OP_FILE holds the done operation
  local id="$1" base="$OP_BASE_PRIMARY" attempt=0 start=$SECONDS code done_flag delay
  err "[poll] operation=$id"
  while :; do
    attempt=$((attempt+1))
    code=$(curl -sS -o "$OP_FILE" -w '%{http_code}' -H "$AUTH_HDR" "$base/$id") || code=000
    if [[ "$code" == "404" && "$base" != "$OP_BASE_FALLBACK" ]]; then
      err "[warn] 404 at $base — falling back to $OP_BASE_FALLBACK"
      base="$OP_BASE_FALLBACK"
      continue
    fi
    if [[ "$code" == "401" || "$code" == "403" ]]; then
      err "[error] auth failed at poll (HTTP $code):"
      cat "$OP_FILE" >&2 || true
      exit 3
    fi
    if [[ "$code" == "200" ]]; then
      done_flag=$(jq -r '.done // false' "$OP_FILE" 2>/dev/null || echo "unparseable")
      if [[ "$done_flag" == "true" ]]; then
        err "[poll] done in $((SECONDS-start))s ($attempt polls)"
        return 0
      fi
      if [[ $VERBOSE -eq 1 ]]; then err "[poll] attempt=$attempt done=$done_flag elapsed=$((SECONDS-start))s"; fi
    else
      err "[warn] poll HTTP $code (attempt $attempt) — retrying"
      if [[ $VERBOSE -eq 1 ]]; then cat "$OP_FILE" >&2 || true; fi
    fi
    if (( SECONDS - start >= TIMEOUT )); then
      echo "operation_id=$id"
      err "[error] poll timeout after ${TIMEOUT}s — result is stored 12 h, retrieve later:"
      err "  yandex-search.sh --fetch $id"
      exit 4
    fi
    if [[ -n "$INTERVAL" ]]; then delay="$INTERVAL"
    elif (( attempt == 1 )); then delay=2
    elif (( attempt == 2 )); then delay=3
    else delay=5
    fi
    sleep "$delay"
  done
}

emit() { # $1 envelope file  $2 meta string → parsed result on stdout
  if [[ $RAW_JSON -eq 1 ]]; then cat "$1"; return 0; fi
  jq -r '.response.rawData // .rawData // .response.data // empty' "$1" > "$B64_FILE"
  if [[ ! -s "$B64_FILE" ]]; then
    err "[error] no rawData in API envelope; first 500 bytes:"
    head -c 500 "$1" >&2 || true
    err ""
    err "[hint] rerun with --raw-json to see the full envelope"
    exit 5
  fi
  if ! base64 -d < "$B64_FILE" > "$PAYLOAD_FILE"; then
    err "[error] base64 decode failed — envelope first 500 bytes:"
    head -c 500 "$1" >&2 || true
    exit 5
  fi
  if [[ $RAW -eq 1 || $HTML_MODE -eq 1 ]]; then
    if [[ $HTML_MODE -eq 1 && $RAW -eq 0 ]]; then
      err "[warn] FORMAT_HTML payload — emitting raw HTML (parser is XML-only)"
    fi
    cat "$PAYLOAD_FILE"
    return 0
  fi
  python3 "$SCRIPT_DIR/yaparse.py" --out "$OUT" --passage-chars "$PASSAGE_CHARS" --meta "$2" < "$PAYLOAD_FILE"
}

# ---------- main flow ----------
if [[ "$MODE" == "fetch" ]]; then
  start=$SECONDS
  poll_op "$OP_ID"
  emit "$OP_FILE" "mode=fetch elapsed=$((SECONDS-start))s ~0₽(paid-at-submit)"
elif [[ "$MODE" == "sync" ]]; then
  start=$SECONDS
  submit
  log_cost sync "$COST_SYNC"
  emit "$RESP_FILE" "mode=sync elapsed=$((SECONDS-start))s ~${COST_SYNC}₽"
else
  start=$SECONDS
  submit
  log_cost async "$COST_ASYNC"
  op_id=$(jq -r '.id // empty' "$RESP_FILE")
  if [[ -z "$op_id" ]]; then
    err "[error] async submit returned no operation id; envelope first 500 bytes:"
    head -c 500 "$RESP_FILE" >&2 || true
    err ""
    exit 5
  fi
  if [[ $NO_WAIT -eq 1 ]]; then
    echo "operation_id=$op_id"
    err "[poll] skipped (--no-wait) — result stored 12 h: yandex-search.sh --fetch $op_id"
    exit 0
  fi
  if [[ "$(jq -r '.done // false' "$RESP_FILE")" == "true" ]]; then
    cp "$RESP_FILE" "$OP_FILE"
    err "[poll] operation=$op_id done immediately"
  else
    poll_op "$op_id"
  fi
  emit "$OP_FILE" "mode=async elapsed=$((SECONDS-start))s ~${COST_ASYNC}₽"
fi
