#!/usr/bin/env bash
# tg-preview.sh <handle> [--before <msg_id>] — публичное превью Telegram-канала
# через t.me/s/<handle> (без MTProto, без API-ключей; только public-каналы).
# Выдаёт последние ~20 постов (полный текст) + msg_id для пагинации.
# Пагинация вглубь: --before <msg_id> (id самого старого поста из прошлой выдачи).
# Канал без веб-превью (приватный/выключено) → TG_NO_PREVIEW, exit 3.
set -uo pipefail
h="${1:?usage: tg-preview.sh <handle> [--before <msg_id>]}"; shift || true
before=""
while [ $# -gt 0 ]; do case "$1" in --before) before="$2"; shift 2;; *) shift;; esac; done
url="https://t.me/s/$h"; [ -n "$before" ] && url="$url?before=$before"
html_page="$(curl -fsSL --max-time 60 -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)' "$url")" \
  || { echo "TG_FETCH_FAIL: $url" >&2; exit 2; }
printf '%s' "$html_page" | python3 -c "
import sys, re, html
t = sys.stdin.read()
# t.me/s/ отдаёт HTML только для каналов с включённым веб-превью.
# Режем на блоки по data-post и внутри каждого ищем текст/время отдельно
# (одним regex'ом с опциональной группой текст терялся — lazy skip).
chunks = re.split(r'data-post=\"', t)[1:]
posts = []
for ch in chunks:
    post_id = ch.split('\"', 1)[0]
    m_text = re.search(r'tgme_widget_message_text[^\"]*\"[^>]*>(.*?)</div>', ch, re.S)
    m_time = re.search(r'<time datetime=\"([^\"]+)\"', ch)
    posts.append((post_id, m_text.group(1) if m_text else '', m_time.group(1) if m_time else '?'))
if not posts:
    print('TG_NO_PREVIEW: канал без веб-превью или не существует (приватный/handle с опечаткой) — это НЕ «постов нет»', file=sys.stderr)
    sys.exit(3)
def clean(s):
    s = re.sub(r'<br/?>', '\n', s or '')
    s = re.sub(r'<[^>]+>', '', s)
    return html.unescape(s).strip()
print(f'# t.me/s: {len(posts)} постов')
for post, body, dt in posts:
    text = clean(body)
    print(f'## {post} | {dt[:16]} | https://t.me/{post}')
    print(text if text else '(медиа-пост без текста)')
    print()
print(f'pagination: --before {posts[0][0].split(\"/\")[-1]}', file=sys.stderr)
" || exit $?
