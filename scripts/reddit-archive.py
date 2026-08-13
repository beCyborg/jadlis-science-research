#!/usr/bin/env python3
"""reddit-archive — no-auth CLI over Arctic Shift + PullPush.

Routing (as in BAScraper): Reddit-wide full-text search -> PullPush,
everything else (exact subreddit, history, comment trees) -> Arctic Shift.

Subcommands:
  search <query> [--limit N]                 PullPush FTS over ALL of Reddit
                                             (submissions + comments, sleep >=4s)
  sub <subreddit> [--after --before --limit] Arctic Shift posts of one subreddit
  comments <submission_id>                   Arctic Shift comment tree (<=25000)

Output: JSON to stdout. No keys, no registration.
Limits as of 2026-08 (volunteer-run, recheck on first 429):
  Arctic Shift ~2000 rpm; PullPush soft 15 / hard 30 rpm -> 4s gap, 1 worker.
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
PULLPUSH = "https://api.pullpush.io/reddit/search"
USER_AGENT = "reddit-archive-cli/1.0 (personal research helper; single worker)"
PULLPUSH_GAP = 4.0  # seconds between PullPush calls, incl. across invocations
# Каталог гарантированно существует на любой машине: иначе write_text падает с OSError,
# он глотается, и троттлинг PullPush молча отключается.
THROTTLE_FILE = Path(os.environ.get("TMPDIR", "/tmp")) / ".reddit-archive-throttle"


def _throttle_pullpush():
    """Keep >=PULLPUSH_GAP seconds between PullPush calls, across processes."""
    try:
        last = float(THROTTLE_FILE.read_text().strip())
    except (OSError, ValueError):
        last = 0.0
    wait = last + PULLPUSH_GAP - time.time()
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
            if "pullpush.io" in full and e.code >= 500:
                hint = ("PullPush is volunteer-run (no SLA), outages happen; "
                        "retry later or use Arctic Shift per-subreddit 'query' FTS")
            print(json.dumps({"error": f"HTTP {e.code}", "url": full, "hint": hint}),
                  file=sys.stderr)
            sys.exit(1)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(json.dumps({"error": str(e), "url": full}), file=sys.stderr)
            sys.exit(1)


def cmd_search(args):
    """PullPush: full-text search across ALL of Reddit."""
    out = {"backend": "pullpush", "query": args.query, "submissions": [], "comments": []}
    _throttle_pullpush()
    data, url = _get(f"{PULLPUSH}/submission/", {"q": args.query, "size": args.limit})
    out["submissions"] = [
        {
            "id": d.get("id"),
            "subreddit": d.get("subreddit"),
            "title": d.get("title"),
            "score": d.get("score"),
            "num_comments": d.get("num_comments"),
            "created_utc": d.get("created_utc"),
            "url": f"https://reddit.com{d.get('permalink', '')}",
            "selftext": (d.get("selftext") or "")[:500],
        }
        for d in data.get("data", [])
    ]
    out["submissions_endpoint"] = url
    _throttle_pullpush()
    data, url = _get(f"{PULLPUSH}/comment/", {"q": args.query, "size": args.limit})
    out["comments"] = [
        {
            "id": d.get("id"),
            "subreddit": d.get("subreddit"),
            "link_id": d.get("link_id"),
            "score": d.get("score"),
            "created_utc": d.get("created_utc"),
            "body": (d.get("body") or "")[:500],
        }
        for d in data.get("data", [])
    ]
    out["comments_endpoint"] = url
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

    s = sub.add_parser("search", help="PullPush full-text search over all of Reddit")
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
