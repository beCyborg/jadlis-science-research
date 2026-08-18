#!/usr/bin/env -S uv run --quiet --with requests
"""substack-fetch.py — свой адаптер Substack (анонимный /api/v1, браузерный UA).

Запуск: прямой (`substack-fetch.py ...`) — шебанг сам тянет
requests через uv (PEP 668: системный python без пакетов).

Замена substack-mcp для чтения: полный текст постов + ПОЛНЫЕ тексты комментариев
(у mcp комментариев нет вовсе). Discovery изданий делается через Brave
`site:substack.com` (см. substack-protocol.md) — глобальный поиск Substack
анонимно не работает (проверено 2026-08-15: search/explore/web игнорирует query;
publication/search и post/search отдают ТИХИЙ ПУСТОЙ результат без 401 — ловушка).

Подкоманды:
  archive <pub> [--limit N] [--search Q] [--offset N]   лента архива: метаданные, реакции,
                                                        счётчики; ?search= работает анонимно
  post <pub> <slug|id>                                  полный текст поста → файл, stdout=путь
  comments <pub> <post_id>                              полное дерево комментариев → файл,
                                                        stdout=путь (post_id — integer из archive)
  search-pub <query>                                    best-effort: publication/search двумя
                                                        путями; пустой ответ = честный exit 3
                                                        (анонимно обычно пусто → Brave discovery)
  notes <pub>                                           best-effort: Notes издания; деградация
                                                        честная (exit 3, не пустой успех)

<pub> — канонический handle (`astralcodexten`, не кастомный домен); кастомные домены
редиректят (301) — requests follow'ит. Кэш: ~/.cache/substack-fetch, ключ из всех argv,
TTL: archive/search 10 мин, post/comments/notes 30 мин.
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
CACHE = os.path.expanduser("~/.cache/substack-fetch")
os.makedirs(CACHE, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json"})


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def base(pub):
    return f"https://{pub}.substack.com"


def get_json(url, params=None):
    r = S.get(url, params=params, timeout=60, allow_redirects=True)
    if r.status_code != 200:
        die(f"HTTP {r.status_code}: {r.url}", 2)
    try:
        return r.json()
    except ValueError:
        die(f"NOT_JSON (вероятно HTML-заглушка/челлендж): {r.url}", 2)


def html_to_md(s):
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p[^>]*>", "\n\n", s)
    s = re.sub(r"<p[^>]*>", "", s)
    s = re.sub(r"<h([1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", s)
    s = re.sub(r"</h[1-6]>", "\n", s)
    s = re.sub(r"<li[^>]*>", "\n- ", s)
    s = re.sub(r"<blockquote[^>]*>", "\n> ", s)
    s = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def cache_path(ext="md"):
    key = hashlib.sha256("|".join(sys.argv[1:]).encode()).hexdigest()[:16]
    return os.path.join(CACHE, f"{key}.{ext}"), key


def cache_fresh(path, ttl):
    return os.path.exists(path) and os.path.getsize(path) > 0 and \
        time.time() - os.path.getmtime(path) < ttl


def post_line(p):
    date = (p.get("post_date") or "")[:10]
    reactions = sum((p.get("reactions") or {}).values()) if isinstance(p.get("reactions"), dict) else (p.get("reaction_count") or 0)
    return (f"## {p.get('title', '?')}\n"
            f"id={p.get('id')} slug={p.get('slug')} | {date} | 👍{reactions} "
            f"💬{p.get('comment_count', 0)} | words={p.get('wordcount', '?')} | "
            f"audience={p.get('audience', '?')}\n"
            f"{p.get('canonical_url', '')}\n"
            f"{(p.get('subtitle') or '').strip()}\n")


def cmd_archive(pub, limit=12, search=None, offset=0):
    out, key = cache_path()
    if cache_fresh(out, 600):
        print(open(out).read())
        print(f"cache=hit key={key}", file=sys.stderr)
        return
    params = {"sort": "new", "limit": min(int(limit), 12), "offset": offset}
    if search:
        params["search"] = search
        params["sort"] = "top"  # search без sort=top на части изданий пуст
    posts = get_json(f"{base(pub)}/api/v1/archive", params)
    if not isinstance(posts, list):
        die(f"UNEXPECTED_SHAPE: {type(posts)}", 2)
    lines = [f"# {pub} — archive" + (f" (search: {search})" if search else "") +
             f" — {len(posts)} постов\n"]
    lines += [post_line(p) for p in posts]
    text = "\n".join(lines)
    open(out, "w").write(text)
    print(text)
    print(f"cache=miss key={key}", file=sys.stderr)


def cmd_post(pub, ref):
    out, key = cache_path()
    if cache_fresh(out, 1800):
        print(out)
        print(f"cache=hit key={key}", file=sys.stderr)
        return
    slug = ref
    if ref.isdigit():  # id → slug через archive невозможно точечно; posts/by-id нет анонимно
        posts = get_json(f"{base(pub)}/api/v1/archive", {"sort": "new", "limit": 12})
        match = [p for p in posts if str(p.get("id")) == ref]
        if not match:
            die(f"POST_ID_NOT_IN_RECENT_ARCHIVE: {ref} — передай slug (из canonical_url)", 2)
        slug = match[0]["slug"]
    p = get_json(f"{base(pub)}/api/v1/posts/{slug}")
    body = html_to_md(p.get("body_html") or "")
    if not body:
        die(f"EMPTY_BODY (пейволл? audience={p.get('audience')}): {slug}", 3)
    text = (f"# {p.get('title', '?')}\n"
            f"{pub} | id={p.get('id')} | {(p.get('post_date') or '')[:10]} | "
            f"audience={p.get('audience')} | 💬{p.get('comment_count', 0)}\n"
            f"{p.get('canonical_url', '')}\n\n"
            f"_{(p.get('subtitle') or '').strip()}_\n\n{body}\n")
    open(out, "w").write(text)
    print(out)
    print(f"cache=miss key={key} chars={len(text)} (читать через Read)", file=sys.stderr)


def render_comment(c, depth, acc):
    body = html_to_md(c.get("body") or "")
    if body:
        date = (c.get("date") or "")[:10]
        name = c.get("name") or "[аноним]"
        reactions = sum((c.get("reactions") or {}).values()) if isinstance(c.get("reactions"), dict) else 0
        pad = "  " * depth
        one = body.replace("\n", " ⏎ ")
        acc.append(f"{pad}- **{name}** ({date}, 👍{reactions}): {one}")
    for ch in c.get("children") or []:
        render_comment(ch, depth + 1, acc)


def cmd_comments(pub, post_id):
    out, key = cache_path()
    if cache_fresh(out, 1800):
        print(out)
        print(f"cache=hit key={key}", file=sys.stderr)
        return
    data = get_json(f"{base(pub)}/api/v1/post/{post_id}/comments")
    comments = data.get("comments") if isinstance(data, dict) else None
    if comments is None:
        die("UNEXPECTED_SHAPE: нет поля comments", 2)
    acc = [f"# {pub} — комментарии к посту {post_id} (полные тексты, дерево)\n"]
    for c in comments:
        render_comment(c, 0, acc)
    hidden = data.get("automod_hidden_comments") or []
    if hidden:
        acc.append(f"\n_automod скрыл {len(hidden)} комментариев_")
    n = sum(1 for line in acc if line.lstrip().startswith("- **"))
    text = "\n".join(acc) + "\n"
    open(out, "w").write(text)
    print(out)
    print(f"cache=miss key={key} comments={n} chars={len(text)} (читать через Read)", file=sys.stderr)


def cmd_search_pub(query):
    # Ключ к непустому анонимному ответу — discovery-заголовки (реверс NHagar/substack_api):
    # Origin/Referer как у страницы substack.com/discover + skipExplanation.
    # Без них API отдаёт ТИХИЙ ПУСТОЙ результат (не 401) — ловушка.
    headers = {"Origin": "https://substack.com",
               "Referer": "https://substack.com/discover"}
    for params in [
        {"query": query, "page": 0, "limit": 25, "skipExplanation": "true", "sort": "relevance"},
        {"query": query, "page": 0},
    ]:
        try:
            r = S.get("https://substack.com/api/v1/publication/search",
                      params=params, headers=headers, timeout=60)
            if r.status_code != 200:
                continue
            d = r.json()
        except (requests.RequestException, ValueError):
            continue
        pubs = d.get("results") or d.get("publications") or (d if isinstance(d, list) else [])
        if pubs:
            for p in pubs[:15]:
                print(f"- {p.get('name', '?')} — {p.get('subdomain', '?')}.substack.com | "
                      f"подписчиков≈{p.get('subscriber_count', '?')} | "
                      f"{(p.get('description') or '')[:120]}")
            return
    die("SEARCH_EMPTY: глобальный поиск изданий анонимно пуст даже с discovery-заголовками "
        "(известная ловушка — пустой ответ вместо 401). Discovery делай через Brave: "
        'site:substack.com "<тема>" (см. substack-protocol.md Layer 0)', 3)


def cmd_notes(pub):
    # Notes издания: reader-feed профиля публикации. Best-effort: у большинства
    # изданий анонимно пусто/404 — честно деградируем.
    for url in [f"{base(pub)}/api/v1/notes",
                f"https://substack.com/api/v1/profile/page/{pub}/notes"]:
        try:
            r = S.get(url, timeout=30, allow_redirects=True)
            if r.status_code != 200:
                continue
            d = r.json()
            items = d.get("items") or d.get("notes") or []
            if items:
                for it in items[:20]:
                    c = it.get("comment") or it
                    body = html_to_md(c.get("body") or "")[:400]
                    if body:
                        print(f"- **{c.get('name', '?')}** ({(c.get('date') or '')[:10]}): "
                              f"{body.replace(chr(10), ' ⏎ ')}")
                return
        except (requests.RequestException, ValueError):
            continue
    die("NOTES_UNAVAILABLE: слой Notes анонимно недоступен для этого издания — "
        "НЕ считать отсутствием Notes; контраргументы ищи через Brave", 3)


def main():
    if len(sys.argv) < 2:
        die(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "archive":
        pub = rest[0]
        kw = {}
        i = 1
        while i < len(rest):
            if rest[i] == "--limit":
                kw["limit"] = rest[i + 1]; i += 2
            elif rest[i] == "--search":
                kw["search"] = rest[i + 1]; i += 2
            elif rest[i] == "--offset":
                kw["offset"] = rest[i + 1]; i += 2
            else:
                die(f"unknown opt: {rest[i]}")
        cmd_archive(pub, **kw)
    elif cmd == "post":
        cmd_post(rest[0], rest[1])
    elif cmd == "comments":
        cmd_comments(rest[0], rest[1])
    elif cmd == "search-pub":
        cmd_search_pub(" ".join(rest))
    elif cmd == "notes":
        cmd_notes(rest[0])
    else:
        die(f"unknown subcommand: {cmd} (archive|post|comments|search-pub|notes)")


if __name__ == "__main__":
    main()
