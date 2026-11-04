#!/usr/bin/env python3
"""yandex-bd.py — Yandex SERP through the Bright Data SERP API (fallback backend of yandex-search.sh).

Bright Data opens https://yandex.ru/search/ through its proxies and returns the raw HTML; this script
parses the organic results into the same output as yaparse.py (text | json | urls).

Why it exists (audit 2026-11-04): the Yandex Search API account was suspended over billing and accepts
RU cards/SBP only for residents. Bench on 9 Russian research queries: 68/90 relevant results in the top
10 vs 57/90 for Brave, `site:` works. Costs: 5 000 requests/month free, then $1.5 per 1 000.
Limits: median 55 s per request (33–82 s), ~1 in 5 first attempts fails (timeout / 502) → timeout 180 s
and one retry. No JSON mode for Yandex (brd_json=1 → 400). Exit node is outside Russia (RU targeting is
forbidden by Bright Data policy); the region comes only from `lr`. Dates are rarely visible (3/90).

Usage: yandex-bd.py "<query>" [--region 225] [--page 0] [--num 10] [--out text|json|urls]
                   [--passage-chars 220] [--timeout 180] [--retries 1]
Keys (env → macOS Keychain via secret.sh): BRIGHTDATA_API_KEY, BRIGHTDATA_ZONE (a SERP API zone).
Exit: 0 ok (incl. 0 results) | 1 usage | 2 no key | 3 API error | 5 HTML not parseable.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.brightdata.com/request"
MON = (r"(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек|қаң|ақп|нау|сәу|мам|мау|шіл|там|қыр|қаз|қар|жел)"
       r"[а-яәіңғүұқөһ]*\.?")
DATE = re.compile(r"\b\d{1,2}\s" + MON + r"(?:\s20\d\d)?\b|\b\d+\s(?:дн[еяь]й?|час[аов]*|күн|сағат)\s(?:назад|бұрын)", re.I)


def err(msg):
    print(msg, file=sys.stderr)


def secret(name):
    v = os.environ.get(name, "").strip()
    if v:
        return v
    try:
        p = subprocess.run(["bash", os.path.join(HERE, "secret.sh"), name], capture_output=True, text=True, timeout=20)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def txt(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def domain(u):
    h = urllib.parse.urlparse(u).hostname or ""
    return h[4:] if h.startswith("www.") else h


def parse(page_html):
    """Organic results of a yandex.ru SERP page (ads, wizards and Yandex-internal links dropped)."""
    items = re.split(r'(?=<li class="serp-item)', page_html)[1:]
    out, seen = [], set()
    for it in items:
        body = re.sub(r"<(svg|style|script|noscript)[\s\S]*?</\1>", "", it[:12000])
        if re.search(r'data-fast-name="[^"]*"', it[:400]):
            continue  # wizard / special block
        if re.search(r'Реклама|Жарнама|yabs\.yandex|data-fast-name="(?:direct|premium)', body[:6000]):
            continue  # ad
        m = re.search(r'<a[^>]*class="[^"]*OrganicTitle-Link[^"]*"[^>]*>', body)
        if not m:
            continue
        hm = re.search(r'href="([^"]+)"', m.group(0))
        if not hm:
            continue
        href = html.unescape(hm.group(1))
        if "tr-page.yandex" in href:
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("url", [href])[0]
        if href.startswith("/") or re.match(r"https?://(?:[a-z]+\.)?yandex\.", href) or href in seen:
            continue
        seen.add(href)
        t = re.search(r"OrganicTitle-LinkText[^>]*>([\s\S]*?)</h2>", body)
        sn = re.search(r"OrganicTextContentSpan[^>]*>([\s\S]*?)</span>\s*</div>", body)
        d = DATE.search(txt(body))
        out.append({"url": href, "title": txt(t.group(1)) if t else "", "domain": domain(href),
                    "modtime": d.group(0) if d else "", "headline": txt(sn.group(1)) if sn else "", "passages": []})
    return out, len(items)


def fetch(key, zone, url, timeout, retries):
    body = json.dumps({"zone": zone, "url": url, "format": "raw"}).encode()
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(API, data=body, headers={"Authorization": "Bearer " + key,
                                                                "Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace"), time.time() - t0
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read()[:300].decode("utf-8", "replace"))
            if e.code in (400, 401, 403):
                break  # not transient
        except Exception as e:  # timeout / network
            last = "%s: %s" % (type(e).__name__, e)
        if attempt < retries:
            err("[warn] bright data attempt %d failed (%s) — retrying" % (attempt + 1, last))
    raise RuntimeError(last or "unknown error")


def emit(out, docs, meta, passage_chars):
    if out == "urls":
        for d in docs:
            print(d["url"])
    elif out == "json":
        print(json.dumps({"found": "n/a", "docs": docs, "meta": meta}, ensure_ascii=False))
    else:
        print("found=n/a docs=%d %s" % (len(docs), meta))
        for i, d in enumerate(docs, 1):
            print("%3d. %s | %s" % (i, d["url"], d["title"] or "(no title)"))
            line = d["headline"] + (" · " + d["modtime"] if d["modtime"] else "")
            if line.strip():
                print("     " + (line if len(line) <= passage_chars else line[:passage_chars - 1] + "…"))


def main():
    ap = argparse.ArgumentParser(description="Yandex SERP via Bright Data (fallback of yandex-search.sh)")
    ap.add_argument("query")
    ap.add_argument("--region", default="225")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--num", type=int, default=10)
    ap.add_argument("--out", choices=["text", "json", "urls"], default="text")
    ap.add_argument("--passage-chars", type=int, default=220)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--retries", type=int, default=1)
    a = ap.parse_args()
    if not a.query.strip():
        err("[error] empty query")
        return 1
    key, zone = secret("BRIGHTDATA_API_KEY"), secret("BRIGHTDATA_ZONE")
    if not key or not zone:
        err("[error] BRIGHTDATA_API_KEY / BRIGHTDATA_ZONE not set — store them in the macOS Keychain (secret.sh --set …)")
        return 2
    params = {"text": a.query, "lr": a.region}
    if a.page:
        params["p"] = a.page
    if a.num and a.num != 10:
        params["numdoc"] = a.num
    url = "https://yandex.ru/search/?" + urllib.parse.urlencode(params)
    try:
        page, lat = fetch(key, zone, url, a.timeout, a.retries)
    except RuntimeError as e:
        err("[error] bright data: %s" % e)
        return 3
    docs, items = parse(page)
    if items == 0:
        err("[error] no serp items in the HTML (captcha or a layout change?); first 300 chars: %r" % page[:300])
        return 5
    err("[cost] brightdata-serp 1 request (free 5k/month, then $0.0015) | %s" % a.query[:60])
    emit(a.out, docs, "backend=brightdata elapsed=%.0fs" % lat, a.passage_chars)
    return 0


if __name__ == "__main__":
    sys.exit(main())
