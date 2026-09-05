#!/usr/bin/env bash
# pdf-fetch.sh <url> [--md] — локальное извлечение PDF, 0 кредитов.
# Env: PDF_FETCH_TTL_DAYS (дефолт 30) — срок жизни кэша; PDF_FETCH_LOCK_SEC (дефолт 60) — ожидание лока.
# Экстракторы: pdftotext (дефолт) / markitdown (--md; markitdown — только docx/xlsx/pptx/pdf, не HTML);
# trafilatura здесь НЕ используется — SIGSEGV в fan-out субагентов (trafilatura#925).
set -uo pipefail
url="${1:?usage: pdf-fetch.sh <url> [--md]}"; fmt="${2:-}"
cache="$HOME/.cache/pdf-fetch"; mkdir -p "$cache"
ttl_days="${PDF_FETCH_TTL_DAYS:-30}"; lock_sec="${PDF_FETCH_LOCK_SEC:-60}"
key="$(printf '%s' "$url" | shasum -a 256 | cut -c1-16)"
ext=txt; [ "$fmt" = "--md" ] && ext=md
pdf="$cache/$key.pdf"; out="$cache/$key.$ext"; lock="$cache/$key.lock.d"
# Портативный лок (нет flock): ждём ≤ lock_sec; протухший лок (> 10 мин) снимаем; по таймауту идём без лока.
locked=0
for _ in $(seq 1 $((lock_sec * 10))); do
  if mkdir "$lock" 2>/dev/null; then locked=1; break; fi
  if [ -n "$(find "$lock" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then rmdir "$lock" 2>/dev/null; fi
  sleep 0.1
done
[ "$locked" = 1 ] && trap 'rmdir "$lock" 2>/dev/null' EXIT
[ "$locked" = 1 ] || echo "pdf-fetch: lock timeout (${lock_sec}s) — continuing without lock" >&2
# cache hit → дедуп; протухший (старше ttl_days) — перекачиваем
if [ -s "$out" ] && [ -z "$(find "$out" -maxdepth 0 -mtime +"$ttl_days" 2>/dev/null)" ]; then printf '%s\n' "$out"; exit 0; fi
ispdf(){ [ -s "$1" ] && [ "$(head -c4 "$1" 2>/dev/null)" = '%PDF' ]; }
tmp="$(mktemp "$cache/$key.XXXXXX")"
curl -fsSL --max-time 90 -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' "$url" -o "$tmp" || true
via=curl
if ! ispdf "$tmp"; then                                                         # JS-gated публичный PDF (НЕ paywall)
  ch="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  [ -x "$ch" ] && "$ch" --headless=new --disable-gpu --no-pdf-header-footer \
     --print-to-pdf="$tmp" --virtual-time-budget=8000 "$url" >/dev/null 2>&1 || true
  via=chrome
fi
ispdf "$tmp" || { rm -f "$tmp"; echo "PDF_UNREACHABLE: $url (JS-gate/скан/paywall — открой ссылку в браузере вручную)" >&2; exit 2; }
mv -f "$tmp" "$pdf"                                                              # atomic
otmp="$(mktemp "$cache/$key.out.XXXXXX")"
if [ "$ext" = md ] && command -v markitdown >/dev/null; then markitdown "$pdf" >"$otmp" 2>/dev/null
else pdftotext -layout "$pdf" "$otmp" 2>/dev/null; fi
chars="$(tr -d '[:space:]' <"$otmp" | wc -c | tr -d ' ')"                       # гард против Chrome-мусора
min=200
if [ "$via" = chrome ]; then
  # Chrome печатает и страницы-заглушки (404 / challenge / login) — они длиннее 200 символов
  # и раньше кэшировались как «PDF». Для Chrome-фолбэка порог выше и маркеры заглушек = отказ.
  min=1000
  if head -c 4000 "$otmp" | grep -qiE 'just a moment|checking your browser|enable javascript|access denied|page not found|404 not found|sign in to continue|log in to continue|are you a robot|captcha'; then
    rm -f "$otmp" "$pdf"; echo "PDF_EMPTY: $url (Chrome-фолбэк отрендерил заглушку — JS-gate/challenge/404)" >&2; exit 2
  fi
fi
if [ "${chars:-0}" -lt "$min" ]; then rm -f "$otmp" "$pdf"; echo "PDF_EMPTY: $url (скан/paywall; ${chars:-0} симв. < $min via $via)" >&2; exit 2; fi
mv -f "$otmp" "$out"                                                            # atomic
pages="$(pdfinfo "$pdf" 2>/dev/null | awk '/^Pages:/{print $2}')" || true
printf '%s\n' "$out"                                                            # stdout = ТОЛЬКО путь
echo "pages=${pages:-?} source=local via=$via credits=0" >&2                    # метаданные → stderr
