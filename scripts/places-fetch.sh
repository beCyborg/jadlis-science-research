#!/usr/bin/env bash
# places-fetch.sh "<текстовый запрос места>" [--fields extra] [--lang ru|pl] [--limit N]
# Google Places API (New) Text Search — place-слой research. Регион по умолчанию PL,
# переопределяется env PLACES_REGION. Тир задаёт X-Goog-FieldMask: дефолтная маска ниже
# включает rating → SKU Enterprise ($35/1000, free tier 1000 событий/мес — при
# research-объёмах бесплатно). НЕ добавляй reviews в маску бездумно (+$5/1000).
#
# ГЕЙТ (руки пользователя, ДО первого вызова): ключ GOOGLE_PLACES_API_KEY в "env"
# файла settings.json (скилл /jadlis-research:keys проводит по шагам) + бюджет-кап
# в Google Cloud Console — hard cap отсутствует by design, budget alert отключает billing.
set -uo pipefail
q="${1:?usage: places-fetch.sh \"<запрос>\" [--lang ru|pl] [--limit N]}"; shift || true
lang=ru; limit=8; region="${PLACES_REGION:-PL}"
while [ $# -gt 0 ]; do case "$1" in
  --lang) lang="$2"; shift 2;; --limit) limit="$2"; shift 2;; *) echo "unknown opt: $1" >&2; exit 1;; esac; done
[ -z "${GOOGLE_PLACES_API_KEY:-}" ] && {
  echo "PLACES_KEY_MISSING: env GOOGLE_PLACES_API_KEY не задан (скилл /jadlis-research:keys)." >&2
  echo "Гейт пользователя: (1) ключ Google Cloud (Places API New), (2) бюджет-кап ДО первого вызова." >&2
  echo "Фоллбэк для агента: mcp__plugin_jadlis-research_brave-search__brave_place_search (country ОБЯЗАТЕЛЕН) — черновик, precision ниже." >&2
  exit 3; }
MASK="places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.priceLevel,places.websiteUri,places.googleMapsUri,places.currentOpeningHours.openNow,places.primaryTypeDisplayName"
curl -fsSL -X POST "https://places.googleapis.com/v1/places:searchText" \
  -H "Content-Type: application/json" \
  -H "X-Goog-Api-Key: $GOOGLE_PLACES_API_KEY" \
  -H "X-Goog-FieldMask: $MASK" \
  -d "$(jq -n --arg q "$q" --arg lang "$lang" --arg region "$region" --argjson n "$limit" \
        '{textQuery:$q, regionCode:$region, languageCode:$lang, pageSize:$n}')" \
  | jq -r '.places[]? | "- **\(.displayName.text)** (\(.primaryTypeDisplayName.text // "?")) — ★\(.rating // "?") (\(.userRatingCount // 0) отзывов)" +
      (if .priceLevel then " | \(.priceLevel)" else "" end) +
      "\n  \(.formattedAddress)" +
      (if .currentOpeningHours.openNow != null then " | сейчас: \(if .currentOpeningHours.openNow then "открыто" else "закрыто" end)" else "" end) +
      "\n  \(.googleMapsUri)" + (if .websiteUri then " | \(.websiteUri)" else "" end)' \
  || { echo "PLACES_API_ERROR (ключ/квота/биллинг?)" >&2; exit 2; }
