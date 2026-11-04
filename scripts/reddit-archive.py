#!/usr/bin/env python3
"""reddit-archive — no-auth CLI over Arctic Shift.

Routing: Reddit-wide keyword search -> the redditapis MCP `reddit_search` (reddit-alt).
Reddit retires RSS on 2026-11-13 (r/modnews 1wubgvt), so `search` no longer calls
www.reddit.com/search.rss: with --sub it runs Arctic Shift title search inside one
subreddit, without --sub it exits 2 with a pointer to the MCP.
Everything else (exact subreddit, history, comment trees) -> Arctic Shift.

Subcommands:
  search <query> --sub S [--fulltext]        Arctic Shift title search in one subreddit
                                             (--fulltext: bodies too, may time out)
  sub <subreddit> [--after --before --limit] Arctic Shift posts of one subreddit
  comments <submission_id> [--compact [N]]   Arctic Shift comment tree (<=25000);
                                             --compact: top-N by score (default 30), flat,
                                             id/parent_id/author/score/depth/body only

Output: JSON to stdout. No keys, no registration.
Limits as of 2026-11 (recheck on first 429): Arctic Shift ~2000 rpm.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ARCTIC = "https://arctic-shift.photon-reddit.com/api"
USER_AGENT = "reddit-archive-cli/1.1 (personal research helper; single worker)"


def _get(url, params, retries=2):
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{qs}"
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8")), full
        except urllib.error.HTTPError as e:
            # Arctic Shift answers 422 «Timeout. Maybe slow down a bit» on a cold query; a retry usually gets 200
            if e.code in (422, 429, 502, 503, 504) and attempt < retries:
                time.sleep(5 * (attempt + 1))
                continue
            print(json.dumps({"error": f"HTTP {e.code}", "url": full}),
                  file=sys.stderr)
            sys.exit(1)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(json.dumps({"error": str(e), "url": full}), file=sys.stderr)
            sys.exit(1)


def cmd_search(args):
    """Keyword search. Reddit-wide search moved to the MCP; in-subreddit search via Arctic Shift."""
    if not args.sub:
        print(json.dumps({
            "error": "reddit-wide search is not available here",
            "hint": "Reddit retires search.rss on 2026-11-13. Use the MCP tool "
                    "mcp__plugin_jadlis-search_reddit-alt__reddit_search for Reddit-wide search, "
                    "or pass --sub <subreddit> for Arctic Shift full-text search in one subreddit."}),
            file=sys.stderr)
        sys.exit(2)
    data, url = _get(f"{ARCTIC}/posts/search",
                     {"subreddit": args.sub, ("query" if args.fulltext else "title"): args.query,
                      "limit": min(args.limit, 100)})
    posts = [{"id": d.get("id"), "subreddit": d.get("subreddit"), "title": d.get("title"),
              "score": d.get("score"), "num_comments": d.get("num_comments"),
              "created_utc": d.get("created_utc"), "url": f"https://reddit.com{d.get('permalink', '')}",
              "selftext": (d.get("selftext") or "")[:500]} for d in data.get("data", [])]
    print(json.dumps({"backend": "arctic-shift", "query": args.query, "subreddit": args.sub,
                      "count": len(posts), "endpoint": url, "submissions": posts},
                     ensure_ascii=False, indent=1))


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


def _flatten(node, out, depth=0):
    """Collect comments from Arctic Shift's nested tree into a flat list with depth."""
    if isinstance(node, list):
        for x in node:
            _flatten(x, out, depth)
        return
    if not isinstance(node, dict):
        return
    d = node.get("data") if node.get("kind") == "t1" and isinstance(node.get("data"), dict) else node
    if isinstance(d, dict) and d.get("body") is not None and d.get("id"):
        out.append({"id": d.get("id"), "parent_id": (d.get("parent_id") or "").split("_")[-1],
                    "author": d.get("author"), "score": d.get("score"), "depth": depth,
                    "body": d.get("body")})
        depth += 1
    for key in ("replies", "children"):
        v = d.get(key) if isinstance(d, dict) else None
        if isinstance(v, dict):
            v = v.get("data", v)
            v = v.get("children", v) if isinstance(v, dict) else v
        if v:
            _flatten(v, out, depth)


def compact_tree(tree, top):
    """Top-N comments by score, without removed/deleted bodies (the size the agent needs)."""
    flat = []
    _flatten(tree, flat)
    seen, keep = set(), []
    for c in flat:
        body = (c.get("body") or "").strip()
        if c["id"] in seen or body in ("[removed]", "[deleted]", ""):
            continue
        seen.add(c["id"])
        keep.append(c)
    keep.sort(key=lambda c: c.get("score") if isinstance(c.get("score"), (int, float)) else -10**9, reverse=True)
    return len(flat), keep[:top]


def cmd_comments(args):
    """Arctic Shift: full comment tree of one submission (or its compact top-N view)."""
    link_id = args.submission_id.removeprefix("t3_")
    data, url = _get(
        f"{ARCTIC}/comments/tree", {"link_id": link_id, "limit": args.limit}
    )
    tree = data.get("data", data)
    if args.compact:
        total, top = compact_tree(tree, args.compact)
        print(json.dumps({"backend": "arctic-shift", "submission_id": link_id, "endpoint": url,
                          "mode": f"compact top-{args.compact} by score", "comments_in_tree": total,
                          "comments": top}, ensure_ascii=False, indent=1))
        return
    print(
        json.dumps(
            {"backend": "arctic-shift", "submission_id": link_id,
             "endpoint": url, "tree": tree},
            ensure_ascii=False, indent=1,
        )
    )


def main():
    p = argparse.ArgumentParser(prog="reddit-archive", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="Arctic Shift full-text search in one subreddit (Reddit-wide: use the MCP)")
    s.add_argument("--sub", help="subreddit to search in (required; Reddit-wide search -> MCP reddit_search)")
    s.add_argument("--fulltext", action="store_true",
                   help="search post bodies too (Arctic `query`; often times out with 422 — default searches titles)")
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
    s.add_argument("--compact", type=int, nargs="?", const=30, default=0,
                   help="flat top-N comments by score (default 30), no removed/deleted")
    s.set_defaults(func=cmd_comments)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
