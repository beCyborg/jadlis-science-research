#!/usr/bin/env python3
"""Co-citation prefilter for backward snowballing (OpenAlex, deterministic, no LLM).

Takes the reviews / meta-analyses already in the corpus, pulls their reference lists and
keeps the works cited by >= --min of them. Measured 2026-09-21 on two topics against the
reference lists of held-out systematic reviews: a random backward reference is on-topic
evidence in 3-6% of cases, a reference shared by >=2 reviews in 20-40%, by >=3 in 46-56%.

Usage:
  cocite.py --hubs W2316232712,10.1093/sleep/33.12.1605,... [--min 2] [--max 40]
            [--seen seen_keys.txt] [--out cocite.json]

--hubs   OpenAlex work ids (W...) and/or DOIs, comma-separated
--seen   file with one normalized DOI per line; those works are dropped from the output
Output:  JSON {hubsResolved, hubsFailed, refsTotal, kept, remainingUsd, papers:[...]}, papers sorted
         by (citedByHubs desc, citations desc). Key: $OPENALEX_API_KEY (works keyless at $0.1/day).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

API = "https://api.openalex.org/works"
KEY = os.environ.get("OPENALEX_API_KEY", "")
remaining_usd = None


def norm_doi(d):
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (d or "").strip().lower())


def get(url):
    global remaining_usd
    err = ""
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jadlis-science-research/cocite"})
            with urllib.request.urlopen(req, timeout=60) as r:
                remaining_usd = r.headers.get("x-ratelimit-remaining-usd", remaining_usd)
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:  # 429 / 5xx / timeout — back off and retry
            err = str(e)
            if getattr(e, "code", None) in (400, 404):  # unknown id — retrying cannot help
                break
            time.sleep(2 + 2 * attempt)
    sys.stderr.write("cocite: request failed: %s\n" % err)
    return {}


def with_key(params):
    if KEY:
        params["api_key"] = KEY
    return urllib.parse.urlencode(params)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hubs", required=True)
    ap.add_argument("--min", type=int, default=2)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--seen", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    seen = set()
    if a.seen and os.path.exists(a.seen):
        seen = {norm_doi(l) for l in open(a.seen, encoding="utf-8") if l.strip()}

    hubs = [h.strip() for h in a.hubs.split(",") if h.strip()]
    counts, resolved, failed = Counter(), [], []
    for h in hubs:
        ident = h if re.match(r"^W\d+$", h, re.I) else "doi:" + norm_doi(h)
        j = get("%s/%s?%s" % (API, urllib.parse.quote(ident, safe=":/"), with_key({"select": "id,referenced_works"})))
        refs = j.get("referenced_works") or []
        if not j.get("id") or not refs:
            failed.append(h)
            continue
        resolved.append(h)
        for r in set(refs):
            counts[r.rsplit("/", 1)[1]] += 1

    hub_ids = {h.upper() for h in hubs if re.match(r"^W\d+$", h, re.I)}
    shared = [(w, n) for w, n in counts.items() if n >= a.min and w.upper() not in hub_ids]

    papers = []
    ids = [w for w, _ in shared]
    for i in range(0, len(ids), 50):
        j = get("%s?%s" % (API, with_key({
            "filter": "openalex:" + "|".join(ids[i:i + 50]), "per_page": 100,
            "select": "id,doi,title,publication_year,type,cited_by_count,fwci,open_access,ids,is_retracted",
        })))
        for r in j.get("results") or []:
            wid = r["id"].rsplit("/", 1)[1]
            doi = norm_doi(r.get("doi"))
            if doi and doi in seen:
                continue
            oa = r.get("open_access") or {}
            pmid = ((r.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1] or None
            papers.append({
                "externalId": wid, "doi": doi or None, "pmid": pmid, "title": r.get("title"),
                "year": r.get("publication_year"), "type": r.get("type"),
                "citations": r.get("cited_by_count"), "fwci": r.get("fwci"),
                "isOA": bool(oa.get("is_oa")), "oaUrl": oa.get("oa_url"),
                "isRetracted": bool(r.get("is_retracted")), "citedByHubs": counts[wid],
            })
    papers.sort(key=lambda p: (-p["citedByHubs"], -(p["citations"] or 0)))
    out = {
        "hubsResolved": len(resolved), "hubsFailed": failed, "refsTotal": len(counts),
        "sharedTotal": len(shared), "kept": min(len(papers), a.max),
        "remainingUsd": remaining_usd, "papers": papers[:a.max],
    }
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(json.dumps({k: v for k, v in out.items() if k != "papers"}, ensure_ascii=False))
    else:
        print(text)


if __name__ == "__main__":
    main()
