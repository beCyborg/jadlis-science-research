#!/usr/bin/env bash
# hn-fetch.sh — своя обёртка HN (Algolia + Firebase), 0 кредитов, полный текст.
# Замена hn-mcp: ключ кэша из ВСЕХ опций (у hn-mcp — только query), реальный
# search_by_date, numericFilters, полное дерево комментариев одним вызовом.
#
# Подкоманды:
#   search <query> [--tags T] [--by-date] [--since D] [--until D] [--points N]
#                  [--limit N] [--page N]     T: story|comment|ask_hn|show_hn|poll|author_<u>|story_<id>
#                  (--tags поддерживает запятую = AND, "(a,b)" = OR по правилам Algolia)
#   thread <id> [--max-comments N]            полное дерево → markdown-файл, stdout = путь
#   user <username>                           профиль + последние комментарии/посты
#   front [top|new|best|ask|show] [--limit N] ленты Firebase (работают и при смерти Algolia)
#   canary                                    свежесть Algolia-индекса (порог 1 ч)
#
# Пагинация >1000 хитов: Algolia отдаёт max 1000; смотри nbHits в шапке → сужай окно
# --since/--until (created_at_i-фильтр) и собирай окна последовательно.
# Degraded-контракт: Algolia умер → exit 3 + "ALGOLIA_DOWN" в stderr; ленты front
# (Firebase) продолжают работать — в отчёте канала честно помечать «поиск недоступен,
# только ленты». Firebase умер тоже → exit 4.
set -uo pipefail
API="https://hn.algolia.com/api/v1"
FB="https://hacker-news.firebaseio.com/v0"
CACHE="$HOME/.cache/hn-fetch"; mkdir -p "$CACHE"
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'

cmd="${1:-}"; [ -z "$cmd" ] && { grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -22 >&2; exit 1; }
shift || true

# ── кэш: ключ = подкоманда + ВСЕ аргументы (фикс бага hn-mcp) ──
KEY="$(printf '%s|%s' "$cmd" "$*" | shasum -a 256 | cut -c1-16)"
ttl() { # TTL сек по подкоманде
  case "$cmd" in search) echo 600;; thread) echo 1800;; user) echo 3600;; front) echo 300;; *) echo 0;; esac; }
cache_fresh() { local f="$CACHE/$KEY.$1" t; t=$(ttl); [ "$t" -gt 0 ] && [ -s "$f" ] && \
  [ $(( $(date +%s) - $(stat -f %m "$f" 2>/dev/null || echo 0) )) -lt "$t" ]; }

jget() { curl -fsSL --max-time 60 -A "$UA" "$1"; }

# HTML → текст (Algolia отдаёт HTML в text/story_text/comment_text)
CLEAN='def clean: (. // "") | gsub("<p>"; "\n\n") | gsub("<br\\s*/?>"; "\n") | gsub("<[^>]+>"; "")
  | gsub("&quot;"; "\"") | gsub("&#x27;"; "'\''") | gsub("&#x2F;"; "/") | gsub("&gt;"; ">")
  | gsub("&lt;"; "<") | gsub("&amp;"; "&") | gsub("\r"; "");'

epoch() { # YYYY-MM-DD | epoch → epoch
  case "$1" in (*[!0-9]*) date -j -f '%Y-%m-%d' "$1" '+%s' 2>/dev/null || { echo "bad date: $1" >&2; exit 1; };;
  (*) echo "$1";; esac; }

canary_check() { # свежесть индекса; stderr-warning при отставании >1 ч (кэш 10 мин)
  local cf="$CACHE/_canary" now age latest
  now=$(date +%s)
  if [ -s "$cf" ] && [ $((now - $(stat -f %m "$cf" 2>/dev/null || echo 0))) -lt 600 ]; then return 0; fi
  latest=$(jget "$API/search_by_date?tags=story&hitsPerPage=1" | jq -r '.hits[0].created_at_i // 0' 2>/dev/null || echo 0)
  [ "${latest:-0}" -eq 0 ] && return 1
  age=$((now - latest))
  echo "$age" > "$cf"
  [ "$age" -gt 3600 ] && echo "HN_INDEX_STALE: свежайший story в Algolia ${age}s назад (>1ч) — индекс может отставать" >&2
  return 0
}

case "$cmd" in
search)
  q="${1:?usage: hn-fetch.sh search <query> [--tags T] [--by-date] [--since D] [--until D] [--points N] [--limit N] [--page N]}"; shift
  tags="" bydate=0 since="" until="" points="" limit=30 page=0
  while [ $# -gt 0 ]; do case "$1" in
    --tags) tags="$2"; shift 2;; --by-date) bydate=1; shift;;
    --since) since="$(epoch "$2")"; shift 2;; --until) until="$(epoch "$2")"; shift 2;;
    --points) points="$2"; shift 2;; --limit) limit="$2"; shift 2;; --page) page="$2"; shift 2;;
    *) echo "unknown opt: $1" >&2; exit 1;; esac; done
  if cache_fresh md; then cat "$CACHE/$KEY.md"; echo "cache=hit key=$KEY" >&2; exit 0; fi
  canary_check || { echo "ALGOLIA_DOWN: поиск HN недоступен. Фоллбэк: 'hn-fetch.sh front top|ask' (Firebase-ленты) + Brave site:news.ycombinator.com; в отчёте пометь «HN-поиск недоступен»." >&2; exit 3; }
  ep=search; [ "$bydate" = 1 ] && ep=search_by_date
  nf=""
  [ -n "$since" ] && nf="created_at_i>=$since"
  [ -n "$until" ] && nf="${nf:+$nf,}created_at_i<$until"
  [ -n "$points" ] && nf="${nf:+$nf,}points>=$points"
  url="$API/$ep?hitsPerPage=$limit&page=$page"
  url="$url&query=$(jq -rn --arg v "$q" '$v|@uri')"
  [ -n "$tags" ] && url="$url&tags=$(jq -rn --arg v "$tags" '$v|@uri')"
  [ -n "$nf" ] && url="$url&numericFilters=$(jq -rn --arg v "$nf" '$v|@uri')"
  resp="$(jget "$url")" || { echo "ALGOLIA_DOWN: $url. Фоллбэк: front-ленты (Firebase) + Brave site:news.ycombinator.com; поиск честно помечать недоступным." >&2; exit 3; }
  out="$CACHE/$KEY.md"
  jq -r --arg q "$q" --arg tags "$tags" --arg ep "$ep" "$CLEAN"'
    "# HN search: \($q) [tags=\($tags) endpoint=\($ep)]",
    "nbHits=\(.nbHits) page=\(.page)/\(.nbPages) (Algolia отдаёт max 1000 хитов; nbHits>1000 → сужай окно --since/--until)",
    "",
    (.hits[] | if (._tags | index("comment")) then
      "## 💬 comment \(.objectID) | \(.author) | \(.created_at[:10]) | on: \(.story_title // "?") (story \(.story_id // "?"))",
      "https://news.ycombinator.com/item?id=\(.objectID)",
      (.comment_text // .text | clean), ""
    else
      "## 📄 \(.title // "(no title)") — story \(.objectID)",
      "points=\(.points // 0) comments=\(.num_comments // 0) | \(.author) | \(.created_at[:10]) | https://news.ycombinator.com/item?id=\(.objectID)" + (if .url then " | \(.url)" else "" end),
      ((.story_text // "") | clean | if . == "" then empty else . end), ""
    end)' <<<"$resp" > "$out" || { echo "PARSE_FAIL search" >&2; exit 1; }
  cat "$out"; echo "cache=miss key=$KEY" >&2
  ;;

thread)
  id="${1:?usage: hn-fetch.sh thread <id> [--max-comments N]}"; shift
  maxc=200
  while [ $# -gt 0 ]; do case "$1" in --max-comments) maxc="$2"; shift 2;; *) shift;; esac; done
  out="$CACHE/$KEY.md"
  if cache_fresh md; then printf '%s\n' "$out"; echo "cache=hit key=$KEY" >&2; exit 0; fi
  if resp="$(jget "$API/items/$id")"; then
    jq -r "$CLEAN"'
      def node(d): ("  " * d) + "- **\(.author // "[deleted]")** (\(.created_at[:10])): " +
        ((.text | clean) | gsub("\n+"; " ⏎ ")), (.children[]? | select(.text or .children) | node(d+1));
      "# \(.title // "thread \(.id)")",
      "story \(.id) | \(.author // "?") | \(.created_at[:10]) | points=\(.points // 0) | https://news.ycombinator.com/item?id=\(.id)" + (if .url then " | \(.url)" else "" end),
      "", ((.text // "") | clean | if . == "" then empty else (. , "") end),
      "## Комментарии (полное дерево, до '"$maxc"')",
      ([.children[]? | node(0)] | .[:'"$maxc"'] | .[])' <<<"$resp" > "$out" 2>/dev/null \
      || { echo "PARSE_FAIL item $id" >&2; exit 1; }
  else
    # degraded: Firebase item + первый уровень комментариев (без полного дерева)
    item="$(jget "$FB/item/$id.json")" || { echo "HN_DOWN: и Algolia, и Firebase недоступны (item $id)" >&2; exit 4; }
    {
      jq -r "$CLEAN"'"# \(.title // "thread \(.id)") [DEGRADED: Algolia недоступен — только 1-й уровень комментариев]",
        "story \(.id) | \(.by // "?") | points=\(.score // 0) | https://news.ycombinator.com/item?id=\(.id)",
        "", ((.text // "") | clean)' <<<"$item"
      echo "## Комментарии (Firebase, 1-й уровень, до 25)"
      for kid in $(jq -r '(.kids // [])[:25][]' <<<"$item"); do
        jget "$FB/item/$kid.json" | jq -r "$CLEAN"'"- **\(.by // "[deleted]")**: " + ((.text | clean) | gsub("\n+"; " ⏎ "))' 2>/dev/null
      done
    } > "$out"
    echo "DEGRADED: Algolia items недоступен, дерево неполное (Firebase 1-й уровень)" >&2
  fi
  printf '%s\n' "$out"
  n=$(grep -c '^\s*- \*\*' "$out" 2>/dev/null || echo 0)
  echo "cache=miss key=$KEY comments=$n (файл читать через Read)" >&2
  ;;

user)
  u="${1:?usage: hn-fetch.sh user <username>}"
  if cache_fresh md; then cat "$CACHE/$KEY.md"; echo "cache=hit key=$KEY" >&2; exit 0; fi
  prof="$(jget "$API/users/$u")" || { echo "ALGOLIA_DOWN или нет пользователя: $u" >&2; exit 3; }
  subs="$(jget "$API/search_by_date?tags=author_$u&hitsPerPage=20")" || subs='{"hits":[]}'
  out="$CACHE/$KEY.md"
  { jq -r "$CLEAN"'"# HN user: \(.username)", "karma=\(.karma) | создан \((.created_at // "?")[:10])",
      ((.about // "") | clean | if . == "" then empty else ("about: " + .) end), "",
      "## Последние 20 сабмитов (by date)"' <<<"$prof"
    jq -r "$CLEAN"'.hits[] | "- [\(._tags | if index("comment") then "comment" else "story" end)] \(.created_at[:10]) \(.title // .story_title // "?") — https://news.ycombinator.com/item?id=\(.objectID)",
      (((.comment_text // "") | clean) | if . == "" then empty else ("  " + (. | gsub("\n+"; " ⏎ ")) | .[:600]) end)' <<<"$subs"
  } > "$out"
  cat "$out"; echo "cache=miss key=$KEY" >&2
  ;;

front)
  type="${1:-top}"; shift || true
  limit=30
  while [ $# -gt 0 ]; do case "$1" in --limit) limit="$2"; shift 2;; *) shift;; esac; done
  case "$type" in top|new|best|ask|show) :;; *) echo "front: top|new|best|ask|show" >&2; exit 1;; esac
  if cache_fresh md; then cat "$CACHE/$KEY.md"; echo "cache=hit key=$KEY" >&2; exit 0; fi
  ids="$(jget "$FB/${type}stories.json")" || { echo "HN_DOWN: Firebase недоступен" >&2; exit 4; }
  out="$CACHE/$KEY.md"
  { echo "# HN front: $type (Firebase, первые $limit)"
    for id in $(jq -r ".[:$limit][]" <<<"$ids"); do echo "$FB/item/$id.json"; done \
      | xargs -P 8 -n 1 curl -fsSL --max-time 30 -A "$UA" 2>/dev/null \
      | jq -r '"- [\(.score // 0)p/\(.descendants // 0)c] \(.title // "?") — https://news.ycombinator.com/item?id=\(.id)" + (if .url then " | \(.url)" else "" end)'
  } > "$out"
  cat "$out"; echo "cache=miss key=$KEY" >&2
  ;;

canary)
  latest=$(jget "$API/search_by_date?tags=story&hitsPerPage=1" | jq -r '.hits[0] | "\(.created_at_i) \(.title)"' 2>/dev/null) \
    || { echo "ALGOLIA_DOWN"; exit 3; }
  age=$(( $(date +%s) - ${latest%% *} ))
  echo "algolia_ok latest_story_age=${age}s title=${latest#* }"
  [ "$age" -gt 3600 ] && { echo "HN_INDEX_STALE (>1ч)" >&2; exit 5; }
  ;;

*) echo "unknown subcommand: $cmd (search|thread|user|front|canary)" >&2; exit 1;;
esac
