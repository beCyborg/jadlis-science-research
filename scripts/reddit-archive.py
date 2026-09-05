#!/usr/bin/env python3
"""reddit-archive — no-auth CLI over Arctic Shift + Reddit search RSS.

Routing: Reddit-wide keyword search -> www.reddit.com/search.rss (browser UA; replaced
PullPush 2026-09-05 — PullPush answers 429 to the first request from any IP since 2026-08-26),
everything else (exact subreddit, history, comment trees) -> Arctic Shift.

Subcommands:
  search <query> [--limit N] [--sub S] [--time year]  Reddit search RSS (posts only;
                                             no comments in RSS — use `comments`)
  sub <subreddit> [--after --before --limit] Arctic Shift posts of one subreddit
  comments <submission_id>                   Arctic Shift comment tree (<=25000)

Output: JSON to stdout. No keys, no registration.
Limits as of 2026-09 (recheck on first 429):
  Arctic Shift ~2000 rpm; search.rss — unofficial, keep >=4s gap, 1 worker.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ARCTIC = "https://arctic-shift.photon-reddit.com/api"
REDDIT_RSS = "https://www.reddit.com/search.rss"
USER_AGENT = "reddit-archive-cli/1.0 (personal research helper; single worker)"
# search.rss answers a script UA with 403/429; a browser UA gets 200 (checked 2026-09-06).
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
RSS_GAP = 4.0  # seconds between search.rss calls, incl. across invocations
# Каталог гарантированно существует на любой машине: иначе write_text падает с OSError,
# он глотается, и троттлинг молча отключается.
THROTTLE_FILE = Path(os.environ.get("TMPDIR", "/tmp")) / ".reddit-archive-throttle"


def _throttle_rss():
    """Keep >=RSS_GAP seconds between search.rss calls, across processes."""
    try:
        last = float(THROTTLE_FILE.read_text().strip())
    except (OSError, ValueError):
        last = 0.0
    wait = last + RSS_GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    try:
        THROTTLE_FILE.write_text(str(time.time()))
    except OSError:
        pass


def _get(url, params, retries=2):
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{qs}"
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8")), full
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < retries:
                time.sleep(5 * (attempt + 1))
                continue
            hint = None
            if "reddit.com" in full and e.code in (403, 429):
                hint = ("reddit search.rss throttled/blocked this IP; do not retry — "
                        "use Arctic Shift per-subreddit 'query' FTS or the MCP")
            print(json.dumps({"error": f"HTTP {e.code}", "url": full, "hint": hint}),
                  file=sys.stderr)
            sys.exit(1)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(json.dumps({"error": str(e), "url": full}), file=sys.stderr)
            sys.exit(1)


def _fetch_rss(url):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            hint = None
            if e.code in (403, 429):
                hint = ("reddit search.rss throttled/blocked this IP; do not retry — "
                        "use Arctic Shift per-subreddit 'query' FTS or the MCP")
            print(json.dumps({"error": f"HTTP {e.code}", "url": url, "hint": hint}), file=sys.stderr)
            sys.exit(1)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 0:
                time.sleep(2)
                continue
            print(json.dumps({"error": str(e), "url": url}), file=sys.stderr)
            sys.exit(1)


def cmd_search(args):
    """Reddit search RSS: keyword search across ALL of Reddit (posts only)."""
    import html as _html
    import re as _re
    import xml.etree.ElementTree as ET
    base = f"https://www.reddit.com/r/{args.sub}/search.rss" if args.sub else REDDIT_RSS
    params = {"q": args.query, "sort": args.sort, "t": args.time, "limit": min(args.limit, 100)}
    if args.sub:
        params["restrict_sr"] = 1
    url = f"{base}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    _throttle_rss()
    raw = _fetch_rss(url)
    out = {"backend": "reddit-search-rss", "query": args.query, "submissions": [], "comments": [],
           "submissions_endpoint": url, "note": "RSS carries posts only; comment trees via `comments <id>`"}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(json.dumps({"error": f"atom parse: {e}", "url": url, "head": raw[:200]}), file=sys.stderr)
        sys.exit(1)
    for ent in root.findall("a:entry", ns):
        link = ent.find("a:link", ns)
        href = link.get("href") if link is not None else ""
        cat = ent.find("a:category", ns)
        content = ent.findtext("a:content", default="", namespaces=ns)
        text = _html.unescape(_re.sub(r"<[^>]+>", " ", content))
        text = _re.sub(r"\s+", " ", text).strip()
        m = _re.search(r"/comments/([a-z0-9]+)/", href or "")
        out["submissions"].append({
            "id": m.group(1) if m else ent.findtext("a:id", default="", namespaces=ns).split("_")[-1],
            "subreddit": cat.get("label", "").replace("r/", "") if cat is not None else None,
            "title": _html.unescape(ent.findtext("a:title", default="", namespaces=ns)),
            "score": None,
            "num_comments": None,
            "created_utc": ent.findtext("a:published", default=None, namespaces=ns) or ent.findtext("a:updated", default=None, namespaces=ns),
            "url": href,
            "selftext": text[:500],
        })
        if len(out["submissions"]) >= args.limit:
            break
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_sub(args):
    """Arctic Shift: posts of one exact subreddit (history-capable)."""
    data, url = _get(
        f"{ARCTIC}/posts/search",
        {
            "subreddit": args.subreddit,
            "limit": args.limit,
            "after": args.after,
            "before": args.before,
            "sort": "desc",
        },
    )
    posts = [
        {
            "id": d.get("id"),
            "title": d.get("title"),
            "author": d.get("author"),
            "score": d.get("score"),
            "num_comments": d.get("num_comments"),
            "created_utc": d.get("created_utc"),
            "url": f"https://reddit.com{d.get('permalink', '')}",
            "selftext": (d.get("selftext") or "")[:500],
        }
        for d in data.get("data", [])
    ]
    print(
        json.dumps(
            {"backend": "arctic-shift", "subreddit": args.subreddit,
             "count": len(posts), "endpoint": url, "posts": posts},
            ensure_ascii=False, indent=1,
        )
    )


def cmd_comments(args):
    """Arctic Shift: full comment tree of one submission."""
    link_id = args.submission_id.removeprefix("t3_")
    data, url = _get(
        f"{ARCTIC}/comments/tree", {"link_id": link_id, "limit": args.limit}
    )
    print(
        json.dumps(
            {"backend": "arctic-shift", "submission_id": link_id,
             "endpoint": url, "tree": data.get("data", data)},
            ensure_ascii=False, indent=1,
        )
    )


def main():
    p = argparse.ArgumentParser(prog="reddit-archive", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="Reddit search RSS: keyword search over all of Reddit (posts)")
    s.add_argument("--sub", help="restrict to one subreddit (r/<sub>/search.rss)")
    s.add_argument("--sort", default="new", choices=["new", "relevance", "top", "comments"])
    s.add_argument("--time", default=None, choices=[None, "hour", "day", "week", "month", "year", "all"], help="time window (t=)")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("sub", help="Arctic Shift posts of an exact subreddit")
    s.add_argument("subreddit")
    s.add_argument("--after", help="ISO date, e.g. 2025-01-01")
    s.add_argument("--before", help="ISO date")
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(func=cmd_sub)

    s = sub.add_parser("comments", help="Arctic Shift comment tree of a submission")
    s.add_argument("submission_id")
    s.add_argument("--limit", type=int, default=25000)
    s.set_defaults(func=cmd_comments)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
