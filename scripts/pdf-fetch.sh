#!/usr/bin/env bash
# pdf-fetch.sh <url> [--md] — локальное извлечение PDF, 0 кредитов.
set -uo pipefail
url="${1:?usage: pdf-fetch.sh <url> [--md]}"; fmt="${2:-}"
cache="$HOME/.cache/pdf-fetch"; mkdir -p "$cache"
key="$(printf '%s' "$url" | shasum -a 256 | cut -c1-16)"
ext=txt; [ "$fmt" = "--md" ] && ext=md
pdf="$cache/$key.pdf"; out="$cache/$key.$ext"; lock="$cache/$key.lock.d"
for _ in $(seq 1 600); do mkdir "$lock" 2>/dev/null && break; sleep 0.1; done   # portable lock (нет flock)
trap 'rmdir "$lock" 2>/dev/null' EXIT
[ -s "$out" ] && { printf '%s\n' "$out"; exit 0; }                              # cache hit → дедуп
ispdf(){ [ -s "$1" ] && [ "$(head -c4 "$1" 2>/dev/null)" = '%PDF' ]; }
tmp="$(mktemp "$cache/$key.XXXXXX")"
curl -fsSL --max-time 90 -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' "$url" -o "$tmp" || true
if ! ispdf "$tmp"; then                                                         # JS-gated публичный PDF (НЕ paywall)
  ch="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  [ -x "$ch" ] && "$ch" --headless=new --disable-gpu --no-pdf-header-footer \
     --print-to-pdf="$tmp" --virtual-time-budget=8000 "$url" >/dev/null 2>&1 || true
fi
ispdf "$tmp" || { rm -f "$tmp"; echo "PDF_UNREACHABLE: $url (JS-gate/скан/paywall — открой ссылку в браузере вручную)" >&2; exit 2; }
mv -f "$tmp" "$pdf"                                                              # atomic
otmp="$(mktemp "$cache/$key.out.XXXXXX")"
if [ "$ext" = md ] && command -v markitdown >/dev/null; then markitdown "$pdf" >"$otmp" 2>/dev/null
else pdftotext -layout "$pdf" "$otmp" 2>/dev/null; fi
chars="$(tr -d '[:space:]' <"$otmp" | wc -c | tr -d ' ')"                       # гард против Chrome-мусора
if [ "${chars:-0}" -lt 200 ]; then rm -f "$otmp" "$pdf"; echo "PDF_EMPTY: $url (скан/paywall)" >&2; exit 2; fi
mv -f "$otmp" "$out"                                                            # atomic
pages="$(pdfinfo "$pdf" 2>/dev/null | awk '/^Pages:/{print $2}')" || true
printf '%s\n' "$out"                                                            # stdout = ТОЛЬКО путь
echo "pages=${pages:-?} source=local credits=0" >&2                            # метаданные → stderr
