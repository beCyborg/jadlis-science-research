#!/usr/bin/env python3
"""Evidence URL health checker for the full-research workflow (urlhealth step).

Reads a JSON array of {prefix, url, quote, snapshotPath} items, then for each item:
  * classifies the URL as ok | blocked | dead (HEAD, then ranged GET; challenge/login
    walls count as blocked, not dead);
  * verifies that the claimed quote is actually present in the local snapshot
    (matched | notFound | notChecked) and reports the snapshot body length
    (snapshotChars; 0 = no snapshot) for the orchestrator's short-snapshot gate;
  * for dead URLs, asks the Wayback Machine whether the page ever existed — no record
    means fabricationSuspect.

Prints one JSON object {items, summary, elapsedSec, partial} to stdout and always
exits 0; work not finished before the global deadline is reported as skipped/notChecked
with partial=true. Stdlib only.
"""

import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Accept-Encoding": "identity",
    "Connection": "close",
}

BLOCKED_CODES = {401, 403, 407, 429, 451, 503}
DEAD_CODES = {404, 410}

# Domains that answer HEAD/GET from a script with a wall no matter what.
# x.com / twitter.com removed 2026-09-05 (schema v4): they go through classify_url now —
# 403/429 -> measured "blocked", 200 + challenge markup -> looks_challenged, 404 -> wayback
# branch + fabricationSuspect. reddit.com stays: www.reddit.com answers 200 with ~6 chars
# of text, reclassifying it would strip HIGH from real claims.
KNOWN_BLOCKED = (
    "reddit.com",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
)

CHALLENGE_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"just a moment",
        r"cf-challenge",
        r"cf_chl_",
        r"checking your browser",
        r"access denied",
        r"enable javascript and cookies",
        r"please enable (?:js|javascript)",
        r"log in to continue",
        r"sign in to continue",
        r"attention required",
        r"captcha",
        r"are you a robot",
        r"unusual traffic",
    )
]
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
SIGNIN_TITLE_RE = re.compile(r"\b(sign in|log ?in|access denied|just a moment)\b", re.I)

MAX_BODY = 65536
PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
WS_RE = re.compile(r"\s+", re.UNICODE)


# --------------------------------------------------------------------------- utils


def now() -> float:
    return time.monotonic()


def normalize(text: str) -> str:
    """lower + ё->е + strip punctuation/quotes + collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = text.lower()
    text = text.replace(" ", " ")
    text = PUNCT_RE.sub(" ", text)
    return WS_RE.sub(" ", text).strip()


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def is_known_blocked(url: str) -> bool:
    host = host_of(url)
    if not host:
        return False
    if host.startswith("old.reddit.com"):
        return False
    for dom in KNOWN_BLOCKED:
        if host == dom or host.endswith("." + dom):
            if dom == "reddit.com" and host.startswith("old."):
                return False
            return True
    return False


def looks_challenged(body: str) -> bool:
    if not body:
        return False
    sample = body[:MAX_BODY]
    for pat in CHALLENGE_PATTERNS:
        if pat.search(sample):
            return True
    m = TITLE_RE.search(sample)
    if m and SIGNIN_TITLE_RE.search(html.unescape(m.group(1))):
        return True
    return False


def decode_body(raw: bytes) -> str:
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return ""


# --------------------------------------------------------------------------- http


class _NoErrorRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 8


def _opener():
    return urllib.request.build_opener(_NoErrorRedirect)


def _request(url: str, method: str, timeout: float, ranged: bool):
    """Return (status, body, error_kind). error_kind in '', 'timeout', 'dns',
    'refused', 'other'."""
    headers = dict(BASE_HEADERS)
    if ranged:
        headers["Range"] = "bytes=0-%d" % (MAX_BODY - 1)
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            body = ""
            if method == "GET":
                body = decode_body(resp.read(MAX_BODY))
            return status, body, ""
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = decode_body(exc.read(MAX_BODY))
        except Exception:
            pass
        return exc.code, body, ""
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.timeout):
            return None, "", "timeout"
        text = str(reason).lower()
        if "timed out" in text:
            return None, "", "timeout"
        if "name or service not known" in text or "nodename nor servname" in text \
                or "getaddrinfo" in text or "name resolution" in text:
            return None, "", "dns"
        if "refused" in text:
            return None, "", "refused"
        return None, "", "other"
    except socket.timeout:
        return None, "", "timeout"
    except Exception:
        return None, "", "other"


def classify_url(url: str, per_url: float):
    """Return (urlStatus, httpStatus, note)."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return "dead", None, "bad-url"
    if is_known_blocked(url):
        return "blocked", None, "known-blocked-domain"

    note = ""
    timeouts = 0

    status, body, err = _request(url, "HEAD", per_url, ranged=False)
    need_get = err != "" or status in (405, 400, 403, 501) or status is None
    if err == "timeout":
        timeouts += 1
    if err in ("dns", "refused"):
        return "dead", None, err
    if status in DEAD_CODES:
        return "dead", status, note

    if need_get:
        status2, body2, err2 = _request(url, "GET", per_url, ranged=True)
        if err2 == "timeout":
            timeouts += 1
            # one retry
            status2, body2, err2 = _request(url, "GET", per_url, ranged=True)
            if err2 == "timeout":
                return "dead", None, "timeout"
        if err2 in ("dns", "refused"):
            return "dead", None, err2
        if err2 == "" and status2 is not None:
            status, body = status2, body2
        elif status is None:
            return "dead", None, err2 or "unreachable"

    if status is None:
        return ("dead", None, "timeout") if timeouts >= 2 else ("blocked", None, "unreachable")

    if status in DEAD_CODES:
        return "dead", status, note
    if status in BLOCKED_CODES:
        return "blocked", status, "http-%d" % status
    if 500 <= status < 600:
        return "blocked", status, "server-error"
    if 200 <= status < 400:
        if looks_challenged(body):
            return "blocked", status, "challenge-page"
        return "ok", status, note
    return "blocked", status, "http-%d" % status


def _wayback_available_api(url: str, timeout: float):
    api = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
    req = urllib.request.Request(api, headers={"User-Agent": UA})
    with _opener().open(req, timeout=timeout) as resp:
        data = json.loads(decode_body(resp.read(200000)) or "{}")
    closest = (data.get("archived_snapshots") or {}).get("closest") or {}
    return bool(closest.get("available"))


def _wayback_cdx(url: str, timeout: float):
    """Fallback: the availability API is often rate-limited (HTTP 429)."""
    api = ("https://web.archive.org/cdx/search/cdx?url="
           + urllib.parse.quote(url, safe="") + "&limit=1&output=json&fl=timestamp")
    req = urllib.request.Request(api, headers={"User-Agent": UA})
    with _opener().open(req, timeout=timeout) as resp:
        rows = json.loads(decode_body(resp.read(200000)) or "[]")
    return bool([r for r in rows[1:] if r])


def wayback_has_record(url: str, timeout: float):
    """Return (available: bool|None, status: 'ok'|'cdx'|'error')."""
    try:
        return _wayback_available_api(url, timeout), "ok"
    except Exception:
        pass
    try:
        return _wayback_cdx(url, timeout), "cdx"
    except Exception:
        return None, "error"


# ---------------------------------------------------------------------- snapshots


def read_snapshot(path: str):
    """Return (text_body, usable: bool)."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read()
    except Exception:
        return "", False
    body = raw
    idx = raw.find("\n---")
    if idx != -1:
        body = raw[idx + 4:]
    body = body.strip()
    if len(body) < 400:
        return body, False
    if looks_challenged(body[:4000]):
        return body, False
    return body, True


def quote_matches(quote: str, snapshot_text: str) -> bool:
    nq = normalize(quote)
    ns = normalize(snapshot_text)
    if not nq or not ns:
        return False
    if len(nq) <= 200:
        return nq in ns
    win = 60
    mid = max(0, (len(nq) - win) // 2)
    windows = [nq[:win], nq[mid:mid + win], nq[-win:]]
    hits = sum(1 for w in windows if w and w in ns)
    return hits >= 2


def resolve_snapshot(item, workdir):
    path = item.get("snapshotPath")
    if path:
        cand = path if os.path.isabs(path) else os.path.join(workdir, path)
        if os.path.isfile(cand):
            return cand
    prefix = item.get("prefix")
    if prefix:
        cand = os.path.join(workdir, "snapshots", "%s.md" % prefix)
        if os.path.isfile(cand):
            return cand
    return None


# ------------------------------------------------------------------------- check


def check_item(item, workdir, per_url, use_wayback):
    started = now()
    prefix = item.get("prefix")
    url = (item.get("url") or "").strip()
    out = {
        "prefix": prefix,
        "url": url,
        "urlStatus": "skipped",
        "httpStatus": None,
        "quoteStatus": "notChecked",
        "snapshotPath": None,
        "fabricationSuspect": False,
        "snapshotChars": 0,
        "waybackStatus": None,
        "note": "",
        "elapsedMs": 0,
    }
    try:
        snap_path = resolve_snapshot(item, workdir)
        out["snapshotPath"] = snap_path
        quote = item.get("quote") or ""
        if snap_path:
            text, usable = read_snapshot(snap_path)
            # body length is reported even when the snapshot is unusable (< 400 chars or a
            # challenge page): the orchestrator's short-snapshot gate keys off this number.
            out["snapshotChars"] = len(text)
            if usable and quote.strip():
                out["quoteStatus"] = "matched" if quote_matches(quote, text) else "notFound"

        status, http_status, note = classify_url(url, per_url)
        out["urlStatus"] = status
        out["httpStatus"] = http_status
        out["note"] = note

        if status == "dead" and use_wayback and note != "bad-url":
            available, wb_status = wayback_has_record(url, per_url)
            out["waybackStatus"] = wb_status
            out["fabricationSuspect"] = bool(wb_status in ("ok", "cdx") and available is False)
    except Exception as exc:  # never raise out of a worker
        out["note"] = "error: %s" % exc.__class__.__name__
        if out["urlStatus"] == "skipped":
            out["urlStatus"] = "blocked"
    out["elapsedMs"] = int((now() - started) * 1000)
    return out


def skipped_item(item, workdir):
    snap_path = resolve_snapshot(item, workdir)
    chars = 0
    if snap_path:
        try:
            chars = len(read_snapshot(snap_path)[0])
        except Exception:
            chars = 0
    return {
        "prefix": item.get("prefix"),
        "url": (item.get("url") or "").strip(),
        "urlStatus": "skipped",
        "httpStatus": None,
        "quoteStatus": "notChecked",
        "snapshotPath": snap_path,
        "fabricationSuspect": False,
        "snapshotChars": chars,
        "waybackStatus": None,
        "note": "deadline",
        "elapsedMs": 0,
    }


def build_summary(items):
    summary = {
        "total": len(items),
        "checked": 0,
        "urlStatus": {"ok": 0, "blocked": 0, "dead": 0, "skipped": 0},
        "quoteStatus": {"matched": 0, "notFound": 0, "notChecked": 0},
        "fabricationSuspect": 0,
    }
    for it in items:
        us = it.get("urlStatus", "skipped")
        summary["urlStatus"][us] = summary["urlStatus"].get(us, 0) + 1
        qs = it.get("quoteStatus", "notChecked")
        summary["quoteStatus"][qs] = summary["quoteStatus"].get(qs, 0) + 1
        if it.get("fabricationSuspect"):
            summary["fabricationSuspect"] += 1
        if us != "skipped":
            summary["checked"] += 1
    return summary


# -------------------------------------------------------------------------- main


def load_input(path):
    if path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("items") or []
    if not isinstance(data, list):
        raise ValueError("input must be a JSON array")
    return [d for d in data if isinstance(d, dict)]


def main():
    started = now()
    ap = argparse.ArgumentParser(description="Check evidence URL health and quote presence.")
    ap.add_argument("--in", dest="inp", required=True, help="JSON array file or '-' for stdin")
    ap.add_argument("--workdir", required=True, help="research workDir (snapshots/ inside)")
    ap.add_argument("--deadline", type=float, default=90.0)
    ap.add_argument("--per-url", dest="per_url", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-wayback", dest="wayback", action="store_false", default=True)
    args = ap.parse_args()

    try:
        items = load_input(args.inp)
    except Exception as exc:
        print(json.dumps({
            "items": [], "summary": build_summary([]),
            "elapsedSec": round(now() - started, 2), "partial": True,
            "error": "input: %s: %s" % (exc.__class__.__name__, exc),
        }, ensure_ascii=False))
        return 0

    workdir = args.workdir
    results = {}
    partial = False
    try:
        pool = cf.ThreadPoolExecutor(max_workers=max(1, args.workers))
        futures = {}
        for idx, item in enumerate(items):
            futures[pool.submit(check_item, item, workdir, args.per_url, args.wayback)] = idx
        remaining = max(0.1, args.deadline - (now() - started))
        done, not_done = cf.wait(futures.keys(), timeout=remaining)
        for fut in done:
            idx = futures[fut]
            try:
                results[idx] = fut.result(timeout=0)
            except Exception:
                results[idx] = skipped_item(items[idx], workdir)
                results[idx]["note"] = "worker-error"
        if not_done:
            partial = True
            for fut in not_done:
                fut.cancel()
        # do not block on hung threads
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        print(json.dumps({
            "items": [], "summary": build_summary([]),
            "elapsedSec": round(now() - started, 2), "partial": True,
            "error": "run: %s: %s" % (exc.__class__.__name__, exc),
        }, ensure_ascii=False))
        return 0

    out_items = []
    for idx, item in enumerate(items):
        out_items.append(results.get(idx) or skipped_item(item, workdir))

    payload = {
        "items": out_items,
        "summary": build_summary(out_items),
        "elapsedSec": round(now() - started, 2),
        "partial": partial,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # last-resort guard: still valid JSON, still exit 0
        print(json.dumps({
            "items": [], "summary": build_summary([]),
            "elapsedSec": 0, "partial": True,
            "error": "%s: %s" % (exc.__class__.__name__, exc),
        }, ensure_ascii=False))
        sys.exit(0)
