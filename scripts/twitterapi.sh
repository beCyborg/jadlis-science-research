#!/usr/bin/env bash
# twitterapi.sh — thin REST wrapper over TwitterAPI.io (Twitter/X data API, pay-per-call).
# Used by the full-research `twitter` channel as a complement to the Grok CLI (replies, author
# profile, trends) and as the keyword-only fallback when Grok is down.
#
# REST is used on purpose instead of the vendor MCP: checked 2026-09-06, the hosted MCP
# (mcp.twitterapi.io) returns empty objects for get_trends and rejects queryType=Top on replies,
# and its tweet objects are flattened. REST returns the full objects.
#
# Key: TWITTERAPI_IO_KEY via scripts/secret.sh (env → macOS Keychain). Exit 2 = no key → the
# caller skips the layer silently. Cost: tweets $0.15 / 1K, profiles $0.18 / 1K, minimum 15
# credits ($0.00015) per call; one 20-tweet page ≈ $0.003.
#
# Usage:
#   twitterapi.sh search  '<query with operators>' [Latest|Top] [cursor]
#   twitterapi.sh replies <tweetId> [Relevance|Latest|Likes] [cursor]
#   twitterapi.sh quotes  <tweetId> [cursor]
#   twitterapi.sh user    <userName>              # profile: bio, followers, createdAt, verified
#   twitterapi.sh last    <userName> [cursor]     # the user's latest tweets
#   twitterapi.sh tweets  <id1,id2,...>           # batch by ids (≤100)
#   twitterapi.sh trends  [woeid] [count]         # 1=Worldwide, 23424975=UK, 23424977=USA, 23424923=Poland
#   twitterapi.sh balance
# Output: raw JSON from the API on stdout. Non-2xx → JSON error on stdout, exit 1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${TWITTERAPI_IO_KEY:-}" ] && [ -x "$HERE/secret.sh" ]; then
  eval "$(bash "$HERE/secret.sh" --export TWITTERAPI_IO_KEY 2>/dev/null || true)"
fi
if [ -z "${TWITTERAPI_IO_KEY:-}" ]; then
  echo '{"error":"no TWITTERAPI_IO_KEY (env or Keychain) — layer skipped"}' >&2
  exit 2
fi

BASE="https://api.twitterapi.io"
UA="jadlis-search/1.0"   # Cloudflare in front of the API blocks requests without a User-Agent
op="${1:-}"; shift || true

req() {  # req <path> [--data-urlencode k=v ...]
  local path="$1"; shift
  local out code
  out=$(curl -sS --max-time 60 -A "$UA" -H "x-api-key: $TWITTERAPI_IO_KEY" \
        -w '\n%{http_code}' --get "$@" "$BASE$path")
  code="${out##*$'\n'}"; out="${out%$'\n'*}"
  printf '%s\n' "$out"
  case "$code" in 2*) return 0;; *) echo "{\"httpError\":$code,\"path\":\"$path\"}" >&2; return 1;; esac
}

case "$op" in
  search)
    q="${1:?query}"; type="${2:-Latest}"; cur="${3:-}"
    req /twitter/tweet/advanced_search --data-urlencode "query=$q" --data-urlencode "queryType=$type" \
        ${cur:+--data-urlencode "cursor=$cur"} ;;
  replies)
    id="${1:?tweetId}"; type="${2:-Relevance}"; cur="${3:-}"
    req /twitter/tweet/replies/v2 --data-urlencode "tweetId=$id" --data-urlencode "queryType=$type" \
        ${cur:+--data-urlencode "cursor=$cur"} ;;
  quotes)
    id="${1:?tweetId}"; cur="${2:-}"
    req /twitter/tweet/quotes --data-urlencode "tweetId=$id" ${cur:+--data-urlencode "cursor=$cur"} ;;
  user)
    req /twitter/user/info --data-urlencode "userName=${1:?userName}" ;;
  last)
    u="${1:?userName}"; cur="${2:-}"
    req /twitter/user/last_tweets --data-urlencode "userName=$u" ${cur:+--data-urlencode "cursor=$cur"} ;;
  tweets)
    req /twitter/tweets --data-urlencode "tweet_ids=${1:?ids}" ;;
  trends)
    req /twitter/trends --data-urlencode "woeid=${1:-1}" --data-urlencode "count=${2:-20}" ;;
  balance)
    req /oapi/my/info ;;
  *)
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 64 ;;
esac
