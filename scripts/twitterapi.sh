#!/usr/bin/env bash
# twitterapi.sh — thin REST wrapper over two X/Twitter data APIs (pay-per-call scrapers, not the
# official X API). Used by the full-research `twitter` channel.
#
# Backends (TWITTER_BACKEND, default auto):
#   auto        TwitterAPI.io first; on HTTP 402 (balance spent) or 5xx → TwittrAPI. Owner decision
#               2026-11-04: switch to TwittrAPI once the TwitterAPI.io balance runs out.
#   twittrapi   TwittrAPI first, TwitterAPI.io on 402/5xx.
#   twitterapiio TwitterAPI.io only.
# Which backend answered is printed to stderr as `backend=<name>`; the JSON shapes differ:
#   TwitterAPI.io: tweets[] / has_next_page / next_cursor / likeCount / author.userName
#   TwittrAPI (format=simple): data[] / hasNextPage / nextCursor / counts.likes / author.username
#
# Keys via scripts/secret.sh (env → macOS Keychain): TWITTERAPI_IO_KEY, TWITTRAPI_API_KEY. Exit 2 =
# neither key → the caller skips the layer silently.
# Cost: TwitterAPI.io tweets $0.15/1K (one 20-tweet page ≈ $0.003, replies up to $0.012/call);
# TwittrAPI $0.0001 per call whatever it returns (header x-price-per-call; bench 2026-11-04: a full
# topic chain $0.0006 vs $0.017, replies on the same tweets identical).
#
# REST on purpose instead of the TwitterAPI.io MCP: checked 2026-09-06, the hosted MCP returned empty
# objects for get_trends and rejected queryType=Top on replies.
#
# Usage:
#   twitterapi.sh search  '<query with operators>' [Latest|Top] [cursor]
#   twitterapi.sh replies <tweetId> [Relevance|Latest|Likes] [cursor]
#   twitterapi.sh quotes  <tweetId> [cursor]
#   twitterapi.sh user    <userName>              # profile: bio, followers, createdAt, verified
#   twitterapi.sh last    <userName> [cursor]     # the user's latest tweets
#   twitterapi.sh tweets  <id1,id2,...>           # batch by ids (≤100)
#   twitterapi.sh trends  [woeid] [count]         # 1=Worldwide, 23424975=UK, 23424977=USA, 23424923=Poland
#   twitterapi.sh balance                         # both backends
# Output: raw JSON from the API on stdout. Non-2xx on every tried backend → JSON error on stderr, exit 1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$HERE/secret.sh" ]; then
  [ -n "${TWITTERAPI_IO_KEY:-}" ] || eval "$(bash "$HERE/secret.sh" --export TWITTERAPI_IO_KEY 2>/dev/null || true)"
  [ -n "${TWITTRAPI_API_KEY:-}" ] || eval "$(bash "$HERE/secret.sh" --export TWITTRAPI_API_KEY 2>/dev/null || true)"
fi
if [ -z "${TWITTERAPI_IO_KEY:-}" ] && [ -z "${TWITTRAPI_API_KEY:-}" ]; then
  echo '{"error":"no TWITTERAPI_IO_KEY or TWITTRAPI_API_KEY (env or Keychain) — layer skipped"}' >&2
  exit 2
fi

BASE="https://api.twitterapi.io"
TBASE="https://api.twittrapi.com"
UA="jadlis-search/1.1"   # Cloudflare in front of the APIs blocks requests without a User-Agent
op="${1:-}"; shift || true

LAST_CODE=0
req() {  # TwitterAPI.io: req <path> [--data-urlencode k=v ...]
  local path="$1"; shift
  local out code
  [ -n "${TWITTERAPI_IO_KEY:-}" ] || { LAST_CODE=401; return 1; }
  out=$(curl -sS --max-time 60 -A "$UA" -H "x-api-key: $TWITTERAPI_IO_KEY" \
        -w '\n%{http_code}' --get "$@" "$BASE$path")
  code="${out##*$'\n'}"; out="${out%$'\n'*}"; LAST_CODE="$code"
  case "$code" in 2*) printf '%s\n' "$out"; echo "backend=twitterapi.io" >&2; return 0;;
    *) echo "{\"httpError\":$code,\"backend\":\"twitterapi.io\",\"path\":\"$path\"}" >&2; return 1;; esac
}
treq() {  # TwittrAPI: treq <path> [--data-urlencode k=v ...]; format=simple always
  local path="$1"; shift
  local out code
  [ -n "${TWITTRAPI_API_KEY:-}" ] || { LAST_CODE=401; return 1; }
  out=$(curl -sS --max-time 60 -A "$UA" -H "X-API-KEY: $TWITTRAPI_API_KEY" \
        -w '\n%{http_code}' --get --data-urlencode "format=simple" "$@" "$TBASE$path")
  code="${out##*$'\n'}"; out="${out%$'\n'*}"; LAST_CODE="$code"
  case "$code" in 2*) printf '%s\n' "$out"; echo "backend=twittrapi" >&2; return 0;;
    *) echo "{\"httpError\":$code,\"backend\":\"twittrapi\",\"path\":\"$path\"}" >&2; return 1;; esac
}
switchable() { case "$LAST_CODE" in 401|402|5*) return 0;; *) return 1;; esac; }  # no key, no balance, server error
run() {  # run "<twitterapi.io call>" "<twittrapi call>" — order by TWITTER_BACKEND, fallback on 402/5xx/no key
  local a="$1" b="$2"
  case "${TWITTER_BACKEND:-auto}" in
    twitterapiio) eval "$a" ;;
    twittrapi)    eval "$b" || { switchable && eval "$a"; } ;;
    *)            eval "$a" || { switchable && { echo "fallback → twittrapi (twitterapi.io HTTP $LAST_CODE)" >&2; eval "$b"; }; } ;;
  esac
}
rank_t() { case "$1" in Latest) echo Recency;; Likes) echo Likes;; *) echo Relevance;; esac; }

case "$op" in
  search)
    q="${1:?query}"; type="${2:-Latest}"; cur="${3:-}"
    run 'req /twitter/tweet/advanced_search --data-urlencode "query=$q" --data-urlencode "queryType=$type" ${cur:+--data-urlencode "cursor=$cur"}' \
        'treq /search --data-urlencode "searchItem=$q" --data-urlencode "category=$type" --data-urlencode "count=20" ${cur:+--data-urlencode "cursor=$cur"}' ;;
  replies)
    id="${1:?tweetId}"; type="${2:-Relevance}"; cur="${3:-}"; rt="$(rank_t "$type")"
    run 'req /twitter/tweet/replies/v2 --data-urlencode "tweetId=$id" --data-urlencode "queryType=$type" ${cur:+--data-urlencode "cursor=$cur"}' \
        'treq "/tweet/$id/replies" --data-urlencode "rankingMode=$rt" ${cur:+--data-urlencode "cursor=$cur"}' ;;
  quotes)
    id="${1:?tweetId}"; cur="${2:-}"
    run 'req /twitter/tweet/quotes --data-urlencode "tweetId=$id" ${cur:+--data-urlencode "cursor=$cur"}' \
        'treq "/tweet/$id/quotes" ${cur:+--data-urlencode "cursor=$cur"}' ;;
  user)
    u="${1:?userName}"
    run 'req /twitter/user/info --data-urlencode "userName=$u"' 'treq "/user/by/username/$u"' ;;
  last)
    u="${1:?userName}"; cur="${2:-}"
    run 'req /twitter/user/last_tweets --data-urlencode "userName=$u" ${cur:+--data-urlencode "cursor=$cur"}' \
        'treq /user/-1/tweets --data-urlencode "username=$u" ${cur:+--data-urlencode "cursor=$cur"}' ;;
  tweets)
    ids="${1:?ids}"
    run 'req /twitter/tweets --data-urlencode "tweet_ids=$ids"' 'treq /tweet/tweets/by/ids --data-urlencode "ids=$ids"' ;;
  trends)
    w="${1:-1}"; n="${2:-20}"
    run 'req /twitter/trends --data-urlencode "woeid=$w" --data-urlencode "count=$n"' 'treq "/trends/$w"' ;;
  balance)
    req /oapi/my/info || true
    treq /balance || true ;;
  *)
    sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 64 ;;
esac
