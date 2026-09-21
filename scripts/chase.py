#!/usr/bin/env python3
"""Citation chasing for one hub paper — the API work of the snowball phase, without an LLM.

Forward (who cites the hub) + backward (the hub's reference list) through OpenAlex; when OpenAlex
cannot serve the hub and a DOI is known, the citation graph comes from OpenCitations Index v2 and
the metadata is hydrated back through OpenAlex (Crossref as the last resort). Already-seen works are
dropped, the rest is ranked by topic-term hits in title+abstract, then by citations.

Why a script: on the 2026-09-21 benchmark run six chase agents spent 24-34 turns each on curl/jq
plumbing, re-reading a 70-100k-token context every turn — the most expensive phase of the run.
The agent now reads one JSON and only judges relevance.

Usage:
  chase.py --hub W2316232712 [--doi 10.5664/jcsm.5100] --terms "melatonin,delayed sleep phase,dlmo"
           [--seen seen.txt] [--max 80] [--out chase_W2316232712.json]

Output: JSON {hub, apiUsed, forwardTotal, backwardTotal, candidates, remainingUsd, note, papers:[...]}
        papers[]: externalId, doi, pmid, title, year, type, citations, fwci, isOA, oaUrl, isRetracted,
                  direction (forward|backward|both), termHits, abstractHead.
Exit 0 even when nothing was found (papers=[]); exit 2 only when no API answered at all.
Key: $OPENALEX_API_KEY (keyless works at $0.1/day); $CROSSREF_MAILTO optional.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

OA = "https://api.openalex.org/works"
OC = "https://api.opencitations.net/index/v2"
KEY = os.environ.get("OPENALEX_API_KEY", "")
MAILTO = os.environ.get("CROSSREF_MAILTO", "")
SELECT = "id,doi,title,publication_year,type,cited_by_count,fwci,open_access,ids,is_retracted,abstract_inverted_index"
remaining_usd = None


def norm_doi(d):
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", (d or "").strip().lower())


def get(url, tries=3):
    global remaining_usd
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jadlis-science-research/chase"})
            with urllib.request.urlopen(req, timeout=60) as r:
                remaining_usd = r.headers.get("x-ratelimit-remaining-usd", remaining_usd)
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            if getattr(e, "code", None) in (400, 404):  # unknown id — retrying cannot help
                return None
            time.sleep(2 + 2 * attempt)
    return None


def oa_url(params=None, ident=None):
    params = dict(params or {})
    if KEY:
        params["api_key"] = KEY
    base = OA if ident is None else "%s/%s" % (OA, urllib.parse.quote(ident, safe=":/"))
    return "%s?%s" % (base, urllib.parse.urlencode(params))


def abstract_head(inv, words=45):
    if not inv:
        return None
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos[:words])


def to_paper(r, direction):
    oa = r.get("open_access") or {}
    pmid = ((r.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1] or None
    return {
        "externalId": r["id"].rsplit("/", 1)[1], "doi": norm_doi(r.get("doi")) or None, "pmid": pmid,
        "title": r.get("title"), "year": r.get("publication_year"), "type": r.get("type"),
        "citations": r.get("cited_by_count"), "fwci": r.get("fwci"), "isOA": bool(oa.get("is_oa")),
        "oaUrl": oa.get("oa_url"), "isRetracted": bool(r.get("is_retracted")), "direction": direction,
        "abstractHead": abstract_head(r.get("abstract_inverted_index")),
    }


def hydrate(filter_key, values, direction):
    out = []
    for i in range(0, len(values), 50):
        j = get(oa_url({"filter": "%s:%s" % (filter_key, "|".join(values[i:i + 50])), "per_page": 100, "select": SELECT}))
        for r in (j or {}).get("results") or []:
            out.append(to_paper(r, direction))
    return out


def crossref_hydrate(dois, direction):
    out = []
    for i in range(0, len(dois), 40):
        q = {"filter": ",".join("doi:" + d for d in dois[i:i + 40]), "rows": 50,
             "select": "DOI,title,issued,type,is-referenced-by-count"}
        if MAILTO:
            q["mailto"] = MAILTO
        j = get("https://api.crossref.org/works?" + urllib.parse.urlencode(q))
        for r in ((j or {}).get("message") or {}).get("items") or []:
            title = (r.get("title") or [None])[0]
            if not title:
                continue
            year = ((r.get("issued") or {}).get("date-parts") or [[None]])[0][0]
            out.append({"externalId": None, "doi": norm_doi(r.get("DOI")), "pmid": None, "title": title, "year": year,
                        "type": r.get("type"), "citations": r.get("is-referenced-by-count"), "fwci": None, "isOA": False,
                        "oaUrl": None, "isRetracted": False, "direction": direction, "abstractHead": None})
        time.sleep(0.4)  # list queries: 3 RPS polite pool
    return out


def via_openalex(hub):
    ident = hub if re.match(r"^W\d+$", hub, re.I) else "doi:" + norm_doi(hub)
    j = get(oa_url({"select": "id,referenced_works,cited_by_count"}, ident))
    if not j or not j.get("id"):
        return None
    wid = j["id"].rsplit("/", 1)[1]
    refs = [r.rsplit("/", 1)[1] for r in j.get("referenced_works") or []]
    backward = hydrate("openalex", refs, "backward")
    forward = []
    # two pulls: the influential citers and the recent ones that citation sort buries
    for sort, n in (("cited_by_count:desc", 100), ("publication_date:desc", 50)):
        k = get(oa_url({"filter": "cites:" + wid, "sort": sort, "per_page": n, "select": SELECT}))
        forward += [to_paper(r, "forward") for r in (k or {}).get("results") or []]
    return {"apiUsed": "openalex", "forwardTotal": j.get("cited_by_count"), "backwardTotal": len(refs), "papers": backward + forward}


def via_opencitations(doi):
    res, totals = [], {}
    for direction, path, field in (("forward", "citations", "citing"), ("backward", "references", "cited")):
        rows = get("%s/%s/doi:%s" % (OC, path, doi))
        if rows is None:
            return None
        dois = []
        for row in rows:
            dois += [t[4:].lower() for t in (row.get(field) or "").split() if t.startswith("doi:")]
        dois = sorted(set(dois))
        totals[direction] = len(dois)
        # OpenCitations returns identifiers only — titles come from OpenAlex, else Crossref
        got = hydrate("doi", dois[:200], direction) or crossref_hydrate(dois[:120], direction)
        res += got
    return {"apiUsed": "opencitations", "forwardTotal": totals.get("forward"), "backwardTotal": totals.get("backward"), "papers": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", required=True, help="OpenAlex W-id or DOI")
    ap.add_argument("--doi", default=None, help="hub DOI for the OpenCitations rung")
    ap.add_argument("--terms", default="", help="comma-separated topic terms / phrases")
    ap.add_argument("--seen", default=None)
    ap.add_argument("--max", type=int, default=80)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    seen = set()
    if a.seen and os.path.exists(a.seen):
        seen = {norm_doi(l) for l in open(a.seen, encoding="utf-8") if l.strip()}
    terms = [t.strip().lower() for t in a.terms.split(",") if t.strip()]
    hub_doi = norm_doi(a.doi) or (norm_doi(a.hub) if not re.match(r"^W\d+$", a.hub, re.I) else "")

    note = ""
    res = via_openalex(a.hub)
    if res is None and hub_doi:
        note = "openalex-fail→opencitations"
        res = via_opencitations(hub_doi)
    if res is None:
        out = {"hub": a.hub, "apiUsed": None, "papers": [], "note": "chase-skip: no API served this hub" + ("" if hub_doi else " (no doi)")}
        text = json.dumps(out, ensure_ascii=False)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(text)
        print(text)
        sys.exit(2)

    merged = {}
    for p in res["papers"]:
        if not p.get("title"):
            continue
        key = p["doi"] or ("ext:" + str(p["externalId"])) if (p["doi"] or p["externalId"]) else "t:" + re.sub(r"\W+", "", p["title"].lower())[:60]
        if p["doi"] and p["doi"] in seen:
            continue
        if key in merged:
            if merged[key]["direction"] != p["direction"]:
                merged[key]["direction"] = "both"
            continue
        hay = ((p["title"] or "") + " " + (p["abstractHead"] or "")).lower()
        p["termHits"] = sum(1 for t in terms if t in hay)
        merged[key] = p
    papers = sorted(merged.values(), key=lambda p: (-p["termHits"], -(p["citations"] or 0)))
    # with topic terms given, a candidate matching none of them is noise from a broad hub
    if terms:
        papers = [p for p in papers if p["termHits"] > 0] or papers[:10]
    out = {"hub": a.hub, "apiUsed": res["apiUsed"], "forwardTotal": res["forwardTotal"], "backwardTotal": res["backwardTotal"],
           "candidates": len(merged), "kept": min(len(papers), a.max), "remainingUsd": remaining_usd, "note": note,
           "papers": papers[:a.max]}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(json.dumps({k: v for k, v in out.items() if k != "papers"}, ensure_ascii=False))
    else:
        print(text)


if __name__ == "__main__":
    main()
