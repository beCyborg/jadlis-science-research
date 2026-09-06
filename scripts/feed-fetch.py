#!/usr/bin/env python3
"""feed-fetch — one shared fetcher for the language layers (ja / zh / ko / eu) of full-research.

RSS 2.0 / Atom / JSON Feed / a few JSON APIs → normalised entries (JSON to stdout) and, on request,
markdown snapshots in the schema v4 shape (header URL: / Date: / Prefix: / Extractor: feed-fetch,
then `---`, then the body). Stdlib only, no keys (Qiita, Stack Exchange and Mastodon work keyless).

Usage:
  feed-fetch.py fetch <feed-url> [--limit N] [--filter REGEX] [--snapshot-dir DIR --prefix P [--start N]]
  feed-fetch.py source <name> <arg> [same options]      # named sources, see SOURCES
  feed-fetch.py sources                                 # list named sources

Named sources (arg in brackets):
  qiita <query>          Qiita API v2 items?query=   (60 req/h per IP — throttled locally)
  hatena <query>         Hatena Bookmark search RSS  (follows the 301; paginate with --page only)
  zenn <topic>           Zenn topic feed
  note <user>            note.com per-author RSS
  v2ex <node>            V2EX node Atom feed (e.g. create, programmer)
  juejin <query>         Juejin — no public feed: returns the Brave query to run instead (exit 3)
  velog <user>           Velog per-user RSS (v2.velog.io/rss/@user)
  tistory <blog>         tistory blog RSS (<blog>.tistory.com/rss)
  disquiet <query>       Disquiet — search target only: returns the Brave query (exit 3)
  stackexchange <site>::<query>   Stack Exchange API v2.3 search/advanced (keyless, 300/day, honours `backoff`)
  mastodon <instance>::<tag>      Mastodon public tag timeline RSS
  dou                    dou.ua forum feed (label UA)
  golem                  golem.de RSS 2.0
  heise                  heise.de Atom (feed only — ClaudeBot rule: never crawl the article body)
  xataka                 xataka.com feed (filler)
  meneame                meneame.net RSS (silent 403 → exit 2)
  wykop <query>          Wykop — API key required (WYKOP_API_KEY, env or Keychain via scripts/secret.sh);
                         without it exit 3 with the Brave query

Exit codes: 0 ok · 2 feed unreachable / empty · 3 source has no feed (use the printed Brave query) · 4 bad args.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
THROTTLE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / ".feed-fetch-throttle"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v]+")

# --------------------------------------------------------------------------- keys


def secret(name):
    """Resolve a key: env var first, then scripts/secret.sh (macOS Keychain standard).

    Silent on any failure — a missing key is a normal degradation path here.
    """
    v = os.environ.get(name, "").strip()
    if v:
        return v
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret.sh")
    if not os.path.exists(script):
        return ""
    try:
        import subprocess

        out = subprocess.run(["bash", script, name], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=15)
    except Exception:
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.decode("utf-8", "replace").strip()


# --------------------------------------------------------------------------- sources

def _brave_hint(query, site, lang):
    return {"backend": "none", "hint": f'No public feed — run Brave: {{"query": "site:{site} {query}", "count": 10}} (query in {lang})', "brave_query": f"site:{site} {query}"}

SOURCES = {
    "qiita":  lambda a: ("https://qiita.com/api/v2/items?per_page=20&query=" + urllib.parse.quote(a), "json-qiita", 60.0),
    "hatena": lambda a: ("https://b.hatena.ne.jp/search/text?q=" + urllib.parse.quote(a) + "&mode=rss", "xml", 2.0),
    "zenn":   lambda a: (f"https://zenn.dev/topics/{urllib.parse.quote(a)}/feed", "xml", 1.0),
    "note":   lambda a: (f"https://note.com/{urllib.parse.quote(a)}/rss", "xml", 1.0),
    "v2ex":   lambda a: (f"https://www.v2ex.com/feed/{urllib.parse.quote(a)}.xml", "xml", 1.0),
    "velog":  lambda a: (f"https://v2.velog.io/rss/@{urllib.parse.quote(a)}", "xml", 1.0),
    "tistory": lambda a: (f"https://{a}.tistory.com/rss", "xml", 1.0),
    "stackexchange": lambda a: ("https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&site="
                                + urllib.parse.quote(a.split("::", 1)[0]) + "&q=" + urllib.parse.quote(a.split("::", 1)[1] if "::" in a else a)
                                + "&filter=withbody&pagesize=20", "json-se", 1.0),
    "mastodon": lambda a: (f"https://{a.split('::', 1)[0]}/tags/{urllib.parse.quote(a.split('::', 1)[1] if '::' in a else a)}.rss", "xml", 1.0),
    "dou":    lambda a: ("https://dou.ua/forums/feed/", "xml", 1.0),
    "golem":  lambda a: ("https://rss.golem.de/rss.php?feed=RSS2.0", "xml", 1.0),
    "heise":  lambda a: ("https://www.heise.de/rss/heise-atom.xml", "xml", 1.0),
    "xataka": lambda a: ("https://www.xataka.com/feedburner.xml", "xml", 1.0),
    "meneame": lambda a: ("https://www.meneame.net/rss", "xml", 1.0),
}
NO_FEED = {
    "juejin":   lambda a: _brave_hint(a, "juejin.cn", "Chinese"),
    "disquiet": lambda a: _brave_hint(a, "disquiet.io", "Korean"),
    "wykop":    lambda a: _brave_hint(a, "wykop.pl", "Polish") if not secret("WYKOP_API_KEY") else None,
}

# --------------------------------------------------------------------------- helpers

def throttle(key, gap):
    THROTTLE_DIR.mkdir(parents=True, exist_ok=True)
    f = THROTTLE_DIR / re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    try:
        last = float(f.read_text().strip())
    except (OSError, ValueError):
        last = 0.0
    wait = last + gap - time.time()
    if wait > 0:
        time.sleep(min(wait, 120))
    try:
        f.write_text(str(time.time()))
    except OSError:
        pass


def get(url, timeout=30, accept="application/atom+xml,application/rss+xml,application/xml,application/json;q=0.9,*/*;q=0.8"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="ignore"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        return e.code, body, dict(e.headers or {})
    except Exception as e:  # dns / timeout / refused
        return None, str(e), {}


def clean(text):
    if not text:
        return ""
    text = html.unescape(TAG_RE.sub(" ", text))
    text = WS_RE.sub(" ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def iso(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return s


def _text(el, *names):
    for n in names:
        for child in el:
            tag = child.tag.split("}")[-1]
            if tag == n:
                if child.text and child.text.strip():
                    return child.text
                # Atom <link href=…>
                if n == "link" and child.get("href"):
                    return child.get("href")
    return ""


def parse_xml(raw):
    root = ET.fromstring(raw)
    tag = root.tag.split("}")[-1]
    out = []
    if tag == "feed":  # Atom
        for e in root:
            if e.tag.split("}")[-1] != "entry":
                continue
            link = ""
            for l in e:
                if l.tag.split("}")[-1] == "link" and (l.get("rel") in (None, "alternate")):
                    link = l.get("href") or ""
                    break
            author = ""
            for a in e:
                if a.tag.split("}")[-1] == "author":
                    author = _text(a, "name")
            out.append({
                "title": clean(_text(e, "title")), "url": link,
                "date": iso(_text(e, "published", "updated")), "author": clean(author),
                "content": clean(_text(e, "content", "summary")),
            })
    else:  # RSS 2.0 / RDF
        for item in root.iter():
            if item.tag.split("}")[-1] != "item":
                continue
            content = ""
            for c in item:
                if c.tag.split("}")[-1] in ("encoded", "description") and c.text:
                    content = c.text if len(c.text) > len(content) else content
            out.append({
                "title": clean(_text(item, "title")), "url": (_text(item, "link") or "").strip(),
                "date": iso(_text(item, "pubDate", "date", "published")), "author": clean(_text(item, "creator", "author")),
                "content": clean(content),
            })
    return out


def parse_json_feed(raw):
    d = json.loads(raw)
    items = d.get("items") if isinstance(d, dict) else d
    out = []
    for it in items or []:
        out.append({"title": clean(it.get("title")), "url": it.get("url") or it.get("external_url") or "",
                    "date": iso(it.get("date_published") or it.get("date_modified")),
                    "author": clean((it.get("author") or {}).get("name") if isinstance(it.get("author"), dict) else it.get("author")),
                    "content": clean(it.get("content_text") or it.get("content_html") or it.get("summary"))})
    return out


def parse_qiita(raw):
    out = []
    for it in json.loads(raw):
        out.append({"title": clean(it.get("title")), "url": it.get("url") or "", "date": iso(it.get("created_at")),
                    "author": (it.get("user") or {}).get("id") or "", "content": clean(it.get("body")),
                    "likes": it.get("likes_count"), "stocks": it.get("stocks_count")})
    return out


def parse_se(raw, headers):
    d = json.loads(raw)
    backoff = d.get("backoff")
    if backoff:
        # the API asks to pause `backoff` seconds before the next call — persist it in the throttle file
        throttle("stackexchange", float(backoff))
    out = []
    for it in d.get("items", []):
        out.append({"title": clean(it.get("title")), "url": it.get("link") or "", "date": iso(str(it.get("creation_date")) and datetime.fromtimestamp(it["creation_date"], timezone.utc).isoformat(timespec="seconds")),
                    "author": (it.get("owner") or {}).get("display_name") or "", "content": clean(it.get("body")),
                    "score": it.get("score"), "answers": it.get("answer_count")})
    return out, {"quota_remaining": d.get("quota_remaining"), "backoff": backoff}


def write_snapshots(entries, snap_dir, prefix, start):
    Path(snap_dir).mkdir(parents=True, exist_ok=True)
    paths = []
    n = start
    for e in entries:
        p = Path(snap_dir) / f"{prefix}{n}.md"
        body = e.get("content") or ""
        head = (f"URL: {e.get('url', '')}\nDate: {(e.get('date') or '')[:10] or datetime.now(timezone.utc).date().isoformat()}\n"
                f"Prefix: [{prefix}{n}]\nExtractor: feed-fetch\nTitle: {e.get('title', '')}\nAuthor: {e.get('author', '')}\n---\n")
        p.write_text(head + body + "\n", encoding="utf-8")
        e["snapshotPath"] = str(p)
        e["snapshotChars"] = len(body)
        paths.append(str(p))
        n += 1
    return paths


# --------------------------------------------------------------------------- main

def run(url, kind, gap, args, key):
    throttle(key, gap)
    if kind == "json-qiita":
        accept = "application/json"
    elif kind == "json-se":
        accept = "application/json"
    else:
        accept = "application/atom+xml,application/rss+xml,application/xml,application/json;q=0.9,*/*;q=0.8"
    if args.page and args.page > 1:
        url += ("&" if "?" in url else "?") + f"page={args.page}"
    status, raw, headers = get(url, accept=accept)
    if status is None or status >= 400 or not raw.strip():
        print(json.dumps({"error": f"HTTP {status}" if status else raw, "url": url, "hint": "feed unreachable/empty — degrade to Brave in the platform language"}, ensure_ascii=False), file=sys.stderr)
        return 2
    meta = {}
    try:
        if kind == "json-qiita":
            entries = parse_qiita(raw)
        elif kind == "json-se":
            entries, meta = parse_se(raw, headers)
        elif raw.lstrip().startswith("{") or raw.lstrip().startswith("["):
            entries = parse_json_feed(raw)
        else:
            entries = parse_xml(raw)
    except Exception as e:
        print(json.dumps({"error": f"parse: {e.__class__.__name__}: {e}", "url": url, "head": raw[:160]}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.filter:
        rx = re.compile(args.filter, re.I)
        entries = [e for e in entries if rx.search((e.get("title") or "") + " " + (e.get("content") or ""))]
    entries = entries[: args.limit]
    for e in entries:
        e["contentChars"] = len(e.get("content") or "")
        if not args.full:
            e["content"] = (e.get("content") or "")[:600]
    paths = []
    if args.snapshot_dir:
        if not args.prefix:
            print("--snapshot-dir requires --prefix", file=sys.stderr)
            return 4
        # snapshots need the full body — refetch is avoided: we sliced only the JSON copy above
        paths = write_snapshots(entries, args.snapshot_dir, args.prefix, args.start)
    print(json.dumps({"backend": "feed-fetch", "source": key, "url": url, "count": len(entries), "entries": entries,
                      "snapshots": paths, "meta": meta, "extractor": "feed-fetch"}, ensure_ascii=False, indent=1))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--limit", type=int, default=20)
    common.add_argument("--filter", help="regex over title+content (case-insensitive) — keep only topic hits")
    common.add_argument("--page", type=int, default=1, help="page= for paginated feeds (Hatena)")
    common.add_argument("--full", action="store_true", help="do not truncate content in the JSON output")
    common.add_argument("--snapshot-dir", dest="snapshot_dir", help="write <prefix>N.md snapshots here")
    common.add_argument("--prefix", help="citation prefix for snapshots, e.g. ja")
    common.add_argument("--start", type=int, default=1, help="first N for <prefix>N.md")
    f = sub.add_parser("fetch", parents=[common]); f.add_argument("url")
    s = sub.add_parser("source", parents=[common]); s.add_argument("name"); s.add_argument("arg", nargs="?", default="")
    sub.add_parser("sources")
    args = ap.parse_args()

    if args.cmd == "sources":
        print("\n".join(sorted(list(SOURCES) + list(NO_FEED))))
        return 0
    if args.cmd == "fetch":
        if not re.match(r"^https?://", args.url):
            print("not a URL", file=sys.stderr); return 4
        return run(args.url, "auto", 1.0, args, "fetch:" + urllib.parse.urlsplit(args.url).netloc)
    name = args.name.lower()
    if name in NO_FEED:
        hint = NO_FEED[name](args.arg)
        if hint is not None:
            print(json.dumps(hint, ensure_ascii=False)); return 3
    if name not in SOURCES:
        print(f"unknown source {name!r}; see `feed-fetch.py sources`", file=sys.stderr); return 4
    url, kind, gap = SOURCES[name](args.arg)
    # snapshot bodies must be full even when JSON output is truncated
    saved_full = args.full
    if args.snapshot_dir:
        args.full = True
    rc = run(url, kind, gap, args, name)
    args.full = saved_full
    return rc


if __name__ == "__main__":
    sys.exit(main())
