#!/usr/bin/env python3
"""Fan-out fetching for the six API sources of search-paper — the API plumbing, without an LLM.

One subcommand per source (pubmed, europepmc, openalex, s2, core, clinicaltrials). Each runs the
passes its protocol prescribes, merges and dedupes them, normalizes every record to one PAPER shape
and writes a single JSON the agent reads once. The agent then only judges relevance and ranks.

Why a script: on the 2026-09-21 benchmark run the fan-out agents spent 14-52 turns each on curl/jq
plumbing (cochrane 52, s2 40, pubmed 28, europepmc 22, clinicaltrials 19, openalex 19, core 18),
re-reading a 70-100k-token context on every turn. The same move in the snowball phase
(scripts/chase.py) took chase agents from 24-34 turns to 6-7.

Usage:
  source-fetch.py <source> --query "<native query string>" [--limit 30] [--year-from YYYY]
                  [--preprints] [--out path]

Output JSON:
  {source, apiStatus: "ok"|"empty"|"unavailable", total, passes:[{name, requested, returned}],
   truncated, remaining, note,
   papers:[{title, doi, pmid, externalId, year, pubTypes, citations, influentialCitations, fwci,
            isOA, oaUrl, abstract, pass, preprint?}]}
A field the API did not return is null — identifiers are never invented.
Exit 0 for ok/empty, 2 for unavailable (the agent then goes to the protocol's documented fallback).

Keys (from env, put there by scripts/secret.sh --export): PUBMED_API_KEY, PUBMED_EMAIL,
OPENALEX_API_KEY, SEMANTIC_SCHOLAR_API_KEY, CORE_API_KEY. Key values are never printed.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ABSTRACT_CAP = 1500
UA = "jadlis-science-research/source-fetch"
THIS_YEAR = datetime.date.today().year

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENALEX = "https://api.openalex.org/works"
S2 = "https://api.semanticscholar.org/graph/v1/paper/search"
CORE = "https://api.core.ac.uk/v3/search/works/"  # the trailing slash is mandatory (301 + HTML else)
CTGOV = "https://clinicaltrials.gov/api/v2/studies"

# PubMed evidence-type pass: 13 hits vs 5 for the unfiltered query on the 2026-09-21 measurement
PT_FILTER = ("(randomized controlled trial[pt] OR meta-analysis[pt] OR systematic review[pt] "
             "OR clinical trial[pt] OR guideline[pt] OR practice guideline[pt])")


# ── pure helpers (unit-tested in tests/test_sp_source_fetch.py) ──────────────────────────────────

def redact(text):
    """Never let a key reach stdout/stderr through an error string or a URL."""
    return re.sub(r"(?i)(api_key|api-key|key|token)=[^&\s'\"]+", r"\1=***", str(text))


def norm_doi(d):
    """Lowercase, resolver prefix stripped; nothing to normalize → None (never an empty string)."""
    d = re.sub(r"^\s*(?:https?://)?(?:dx\.)?doi\.org/", "", (d or "").strip(), flags=re.I)
    d = d.strip().lower()
    return d or None


def cap_abstract(text, cap=ABSTRACT_CAP):
    """Whitespace-collapsed abstract of at most `cap` characters; empty → None."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return None
    return t if len(t) <= cap else t[:cap - 1].rstrip() + "…"


def abstract_from_inverted_index(inv, cap=ABSTRACT_CAP):
    """OpenAlex ships abstracts as {word: [positions]} — put the words back in order."""
    if not inv:
        return None
    pos = sorted((p, w) for w, ps in (inv or {}).items() for p in (ps or []))
    return cap_abstract(" ".join(w for _, w in pos), cap)


def first_year(text):
    m = re.search(r"(?:19|20)\d{2}", str(text or ""))
    return int(m.group(0)) if m else None


def paper(title, doi=None, pmid=None, external_id=None, year=None, pub_types=None, citations=None,
          influential=None, fwci=None, is_oa=None, oa_url=None, abstract=None, pass_name=None,
          **extra):
    """The one PAPER shape every source normalizes into."""
    rec = {
        "title": title or None, "doi": norm_doi(doi), "pmid": str(pmid) if pmid else None,
        "externalId": external_id or None, "year": year, "pubTypes": [p for p in (pub_types or []) if p],
        "citations": citations, "influentialCitations": influential, "fwci": fwci,
        "isOA": is_oa, "oaUrl": oa_url or None, "abstract": cap_abstract(abstract),
        "pass": pass_name,
    }
    rec.update(extra)
    return rec


def paper_key(p):
    if p.get("doi"):
        return "doi:" + p["doi"]
    if p.get("pmid"):
        return "pmid:" + str(p["pmid"])
    if p.get("externalId"):
        return "ext:" + str(p["externalId"])
    return "t:" + re.sub(r"\W+", "", (p.get("title") or "").lower())[:60]


def merge_passes(groups, limit, extras=None):
    """groups: [(name, [papers])] in priority order. Dedupe, cut to `limit`, then append `extras`
    (preprints — they ride on top of the LIMIT budget, per the Europe PMC protocol)."""
    seen, merged, passes = set(), [], []
    for name, rows in groups:
        kept = 0
        for p in rows:
            k = paper_key(p)
            if k in seen:
                continue
            seen.add(k)
            merged.append(p)
            kept += 1
        passes.append({"name": name, "requested": None, "returned": len(rows), "new": kept})
    merged = merged[:limit]
    seen = set(paper_key(p) for p in merged)
    for p in extras or []:
        k = paper_key(p)
        if k not in seen:
            seen.add(k)
            merged.append(p)
    return merged, passes


def epmc_status(payload):
    """FAILURE CRITERION (europe-pmc-protocol.md): a body without `hitCount` means the source is
    down whatever the HTTP status said — 21.09.2026 it answered 200 with `{"version":"6.9"}`.
    `hitCount: 0` is a legitimate empty result, not a failure."""
    if not isinstance(payload, dict) or "hitCount" not in payload:
        return "unavailable"
    try:
        hits = int(payload.get("hitCount") or 0)
    except (TypeError, ValueError):
        return "unavailable"
    return "ok" if hits > 0 else "empty"


def parse_pubmed_xml(xml_text):
    """efetch `rettype=abstract&retmode=xml` → PAPER records (abstract, pubTypes, year, DOI, PMID).

    Handles both `PubmedArticle` (journal) and `PubmedBookArticle` (book chapters such as Endotext
    or StatPearls) — a PMID whose record is a book otherwise comes back without any metadata."""
    try:
        root = ET.fromstring(xml_text or "")
    except ET.ParseError:
        return []
    out = []
    for art in root.iter("PubmedArticle"):
        cit = art.find("MedlineCitation")
        article = cit.find("Article") if cit is not None else None
        if article is None:
            continue
        out.append(_pubmed_record(
            art, pmid=_text(cit.find("PMID")),
            title=_text(article.find("ArticleTitle")),
            abstract_root=article,
            year=(first_year(_text(article.find("Journal/JournalIssue/PubDate")))
                  or first_year(_text(article.find("ArticleDate")))),
            pub_types=[_text(pt) for pt in article.iter("PublicationType")],
            journal=_text(article.find("Journal/Title")),
        ))
    for art in root.iter("PubmedBookArticle"):
        doc = art.find("BookDocument")
        if doc is None:
            continue
        book = doc.find("Book")
        out.append(_pubmed_record(
            art, pmid=_text(doc.find("PMID")),
            title=(_text(doc.find("ArticleTitle")) or _text(book.find("BookTitle")) if book is not None else ""),
            abstract_root=doc,
            year=first_year(_text(book.find("PubDate")) if book is not None else ""),
            pub_types=[_text(pt) for pt in doc.iter("PublicationType")] or ["Book Chapter"],
            journal=(_text(book.find("BookTitle")) if book is not None else ""),
        ))
    return out


def _pubmed_record(art, pmid, title, abstract_root, year, pub_types, journal):
    chunks = []
    for ab in abstract_root.iter("AbstractText"):
        body = _text(ab)
        if not body:
            continue
        label = (ab.get("Label") or "").strip()
        chunks.append("%s: %s" % (label.capitalize(), body) if label else body)
    doi = None
    for aid in art.iter("ArticleId"):
        if (aid.get("IdType") or "").lower() == "doi":
            doi = _text(aid)
            break
    return paper(
        title=title or None, doi=doi, pmid=pmid or None, external_id=pmid or None, year=year,
        pub_types=pub_types, abstract=" ".join(chunks) or None, journal=journal or None,
    )


def core_record(raw, pass_name="core"):
    """CORE ships `fullText` (80-180k chars per record) inside search results — it must never be
    emitted; only the boolean `hasFullText` survives."""
    raw = raw or {}
    return paper(
        title=raw.get("title"), doi=raw.get("doi"), external_id=str(raw["id"]) if raw.get("id") else None,
        year=raw.get("yearPublished"), pub_types=[raw.get("documentType")],
        is_oa=bool(raw.get("downloadUrl")), oa_url=raw.get("downloadUrl"),
        abstract=raw.get("abstract"), pass_name=pass_name,
        hasFullText=bool(raw.get("fullText")),
        repository=((raw.get("dataProviders") or [{}])[0] or {}).get("name"),
    )


def _text(node):
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip() if node is not None else ""


# ── HTTP ─────────────────────────────────────────────────────────────────────────────────────────

def request(url, headers=None, tries=3, raw=False, pause=2.0):
    """(payload, response headers) or (None, {"_error": …}). No retry on 400/404 — an unknown id or
    a malformed query cannot be fixed by asking again; 429 backs off longer."""
    last = ""
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=90) as r:
                body = r.read().decode("utf-8", "ignore")
                got = dict((k.lower(), v) for k, v in r.headers.items())
                return (body if raw else json.loads(body)), got
        except Exception as e:
            last = redact(e)
            code = getattr(e, "code", None)
            if code in (400, 404):
                break
            if attempt < tries - 1:
                time.sleep((5.0 if code == 429 else pause) * (attempt + 1))
    return None, {"_error": last}


def envelope(source, status, papers=None, total=None, passes=None, remaining=None, note=""):
    papers = papers or []
    return {
        "source": source, "apiStatus": status, "total": total, "passes": passes or [],
        "truncated": bool(total is not None and total > len(papers)),
        "remaining": remaining, "note": note.strip(), "papers": papers,
    }


def third(limit):
    return max(1, int(round(limit / 3.0)))


# ── sources ──────────────────────────────────────────────────────────────────────────────────────

def fetch_pubmed(a):
    """Two passes (evidence-type at 2/3 of LIMIT + general at 1/3), `sort=relevance` always,
    then efetch for abstracts, publication types, year and DOI."""
    key, email = os.environ.get("PUBMED_API_KEY", ""), os.environ.get("PUBMED_EMAIL", "")
    base = a.query
    if a.year_from:
        base = "(%s) AND %d:%d[dp]" % (base, a.year_from, THIS_YEAR)
    plan = [("evidence", "(%s) AND %s" % (base, PT_FILTER), max(1, a.limit - third(a.limit))),
            ("general", base, third(a.limit))]

    ids_by_pass, counts, passes, failures = [], {}, [], 0
    for name, term, retmax in plan:
        params = {"db": "pubmed", "term": term, "retmax": retmax, "sort": "relevance", "retmode": "json",
                  "tool": "search-paper"}
        if email:
            params["email"] = email
        if key:
            params["api_key"] = key
        j, h = request(EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(params))
        res = (j or {}).get("esearchresult") or {}
        ids = [str(i) for i in (res.get("idlist") or [])]
        if j is None or "esearchresult" not in (j or {}):
            failures += 1
        counts[name] = first_year_free_int(res.get("count"))
        ids_by_pass.append((name, ids))
        passes.append({"name": name, "requested": retmax, "returned": len(ids)})
        time.sleep(0.12)  # 10 RPS with an API key
    if failures == len(plan):
        return envelope("pubmed", "unavailable", note="esearch did not answer after retries"), 2

    order, want = {}, []
    for name, ids in ids_by_pass:
        for pmid in ids:
            if pmid not in order:
                order[pmid] = name
                want.append(pmid)
    records = {}
    for i in range(0, len(want), 200):
        xml, _ = request(EUTILS + "/efetch.fcgi?" + urllib.parse.urlencode(dict(
            [("db", "pubmed"), ("id", ",".join(want[i:i + 200])), ("rettype", "abstract"),
             ("retmode", "xml"), ("tool", "search-paper")] + ([("api_key", key)] if key else []))), raw=True)
        for rec in parse_pubmed_xml(xml or ""):
            if rec.get("pmid"):
                records[rec["pmid"]] = rec
        time.sleep(0.12)

    groups, note = [], ""
    for name, ids in ids_by_pass:
        rows = []
        for pmid in ids:
            rec = records.get(pmid)
            if rec is None:  # esummary/efetch did not return it — keep the id, never invent metadata
                rec = paper(title=None, pmid=pmid, external_id=pmid)
                note = "some PMIDs came back without efetch metadata"
            rec = dict(rec)
            rec["pass"] = order.get(pmid, name)
            rows.append(rec)
        groups.append((name, rows))
    papers, merged_passes = merge_passes(groups, a.limit)
    for p, src in zip(merged_passes, passes):
        p["requested"] = src["requested"]
    total = counts.get("general")
    note = (note + " | " if note else "") + "evidence-pass hits: %s" % counts.get("evidence")
    status = "ok" if papers else "empty"
    return envelope("pubmed", status, papers, total, merged_passes, note=note), 0


def first_year_free_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fetch_europepmc(a):
    """Pass 1 `sort=CITED desc`, pass 2 recency (FIRST_PDATE window, `P_PDATE_D desc`, a third of
    LIMIT); `--preprints` adds `AND SRC:PPR` on top of the LIMIT budget."""
    def search(query, page_size, sort, delay=3.0):
        """Retry once after `delay` on the protocol's failure criterion. The retry lives here and
        not in `request`: Europe PMC fails with HTTP 200 and a body without `hitCount`, which the
        transport layer has no way to see as an error."""
        params = {"query": query, "format": "json", "pageSize": page_size, "resultType": "core"}
        if sort:
            params["sort"] = sort
        url = EPMC + "?" + urllib.parse.urlencode(params)
        j, _ = request(url, tries=1)
        if epmc_status(j) == "unavailable":
            time.sleep(delay)
            j, _ = request(url, tries=1)
        return j

    q = a.query
    if a.year_from:
        q = "(%s) AND (FIRST_PDATE:[%d TO %d])" % (q, a.year_from, THIS_YEAR)
    j = search(q, a.limit, "CITED desc")
    status = epmc_status(j)
    if status == "unavailable":
        return envelope("europe-pmc", "unavailable",
                        note="no hitCount field in the response — source down regardless of HTTP status"), 2

    total = first_year_free_int(j.get("hitCount"))
    groups = [("cited", [epmc_record(r, "cited") for r in _epmc_rows(j)])]

    lo = max(a.year_from or 0, THIS_YEAR - 3)
    rq = "(%s) AND (FIRST_PDATE:[%d TO %d])" % (a.query, lo, THIS_YEAR)
    jr = search(rq, third(a.limit), "P_PDATE_D desc", delay=2.0)
    note = "" if epmc_status(jr) != "unavailable" else "recency pass did not answer"
    groups.append(("recent", [epmc_record(r, "recent") for r in _epmc_rows(jr)]))

    extras = []
    if a.preprints:
        pq = "(%s) AND SRC:PPR" % a.query
        jp = search(pq, 10, "P_PDATE_D desc", delay=2.0)
        if epmc_status(jp) == "ok" and not _epmc_rows(jp):
            jp = search(pq, 10, None, delay=2.0)  # the protocol's documented sort fallback
            note = (note + "; " if note else "") + "preprint pass ran without sort"
        extras = [epmc_record(r, "preprint", preprint=True) for r in _epmc_rows(jp)]
        extras.sort(key=lambda p: (p.get("year") or 0), reverse=True)

    papers, passes = merge_passes(groups, a.limit, extras)
    passes[0]["requested"] = a.limit
    passes[1]["requested"] = third(a.limit)
    if a.preprints:
        passes.append({"name": "preprints", "requested": 10, "returned": len(extras)})
    return envelope("europe-pmc", "ok" if papers else "empty", papers, total, passes, note=note), 0


def _epmc_rows(j):
    return ((j or {}).get("resultList") or {}).get("result") or []


def epmc_record(r, pass_name, preprint=False):
    urls = ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
    oa = next((u.get("url") for u in urls if (u.get("availability") or "").lower().startswith("open")), None)
    rec = paper(
        title=r.get("title"), doi=r.get("doi"), pmid=r.get("pmid"),
        external_id=("%s:%s" % (r.get("source"), r.get("id")) if r.get("id") else None),
        year=first_year_free_int(r.get("pubYear")),
        pub_types=((r.get("pubTypeList") or {}).get("pubType") or []),
        citations=first_year_free_int(r.get("citedByCount")),
        is_oa=(r.get("isOpenAccess") == "Y"), oa_url=oa,
        abstract=r.get("abstractText"), pass_name=pass_name,
        journal=(r.get("journalTitle") or None),
    )
    if preprint:
        rec["preprint"] = True
        rec["date"] = r.get("firstPublicationDate")
    return rec


def fetch_openalex(a):
    """`filter=title_and_abstract.search:` + `sort=cited_by_count:desc`, then a relevance pass over
    the last 3 years at a third of LIMIT. `search=` (full text) + citation sort surfaces famous
    papers that mention the term in passing — 0 hits in TOP-50 on the 21.09.2026 measurement."""
    key = os.environ.get("OPENALEX_API_KEY", "")
    select = ("id,doi,title,publication_year,type,cited_by_count,fwci,open_access,ids,"
              "abstract_inverted_index,primary_location")
    note = ""
    q = a.query
    if "," in q:  # a comma separates filters in the OpenAlex filter grammar
        q = q.replace(",", " ")
        note = "commas in the query replaced by spaces (OpenAlex filter separator)"

    def call(filters, sort, per_page):
        params = {"filter": ",".join(filters), "per_page": per_page, "select": select}
        if sort:
            params["sort"] = sort
        if key:
            params["api_key"] = key
        return request(OPENALEX + "?" + urllib.parse.urlencode(params))

    base = ["title_and_abstract.search:" + q]
    if a.year_from:
        base.append("from_publication_date:%d-01-01" % a.year_from)
    j, h = call(base, "cited_by_count:desc", a.limit)
    if j is None:
        time.sleep(3)
        j, h = call(base, "cited_by_count:desc", a.limit)
    if j is None:
        return envelope("openalex", "unavailable", note="works endpoint did not answer after a retry"), 2
    remaining = h.get("x-ratelimit-remaining-usd")
    total = ((j.get("meta") or {}).get("count"))

    recent = base[:1] + ["from_publication_date:%d-01-01" % max(a.year_from or 0, THIS_YEAR - 3)]
    jr, hr = call(recent, None, third(a.limit))
    remaining = (hr or {}).get("x-ratelimit-remaining-usd", remaining)
    groups = [("cited", [openalex_record(r, "cited") for r in (j.get("results") or [])]),
              ("recent", [openalex_record(r, "recent") for r in ((jr or {}).get("results") or [])])]
    papers, passes = merge_passes(groups, a.limit)
    passes[0]["requested"] = a.limit
    passes[1]["requested"] = third(a.limit)
    return envelope("openalex", "ok" if papers else "empty", papers, total, passes,
                    remaining=remaining, note=note), 0


def openalex_record(r, pass_name):
    oa = r.get("open_access") or {}
    pmid = ((r.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1] or None
    loc = (r.get("primary_location") or {}).get("source") or {}
    return paper(
        title=r.get("title"), doi=r.get("doi"), pmid=pmid,
        external_id=(r.get("id") or "").rsplit("/", 1)[-1] or None,
        year=r.get("publication_year"), pub_types=[r.get("type")],
        citations=r.get("cited_by_count"), fwci=r.get("fwci"),
        is_oa=bool(oa.get("is_oa")), oa_url=oa.get("oa_url"),
        abstract=abstract_from_inverted_index(r.get("abstract_inverted_index")),
        pass_name=pass_name, journal=loc.get("display_name"),
    )


def fetch_s2(a):
    """Relevance search. 1 RPS per key — calls are spaced, 429 backs off (see `request`)."""
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    fields = ("title,authors,year,abstract,citationCount,influentialCitationCount,publicationTypes,"
              "journal,externalIds,isOpenAccess,openAccessPdf,fieldsOfStudy")
    params = {"query": a.query, "limit": min(a.limit, 100), "fields": fields}
    if a.year_from:
        params["year"] = "%d-" % a.year_from
    headers = {"x-api-key": key} if key else {}
    time.sleep(1.1)
    j, _ = request(S2 + "?" + urllib.parse.urlencode(params), headers=headers, pause=3.0)
    if j is None:
        return envelope("s2", "unavailable",
                        note="paper/search did not answer after retries" + ("" if key else "; no API key in env")), 2
    rows = [s2_record(r, "relevance") for r in (j.get("data") or [])]
    papers, passes = merge_passes([("relevance", rows)], a.limit)
    passes[0]["requested"] = min(a.limit, 100)
    return envelope("s2", "ok" if papers else "empty", papers, first_year_free_int(j.get("total")),
                    passes, note="" if key else "no SEMANTIC_SCHOLAR_API_KEY in env — shared pool"), 0


def s2_record(r, pass_name):
    ext = r.get("externalIds") or {}
    pdf = r.get("openAccessPdf") or {}
    return paper(
        title=r.get("title"), doi=ext.get("DOI"), pmid=ext.get("PubMed"), external_id=r.get("paperId"),
        year=r.get("year"), pub_types=(r.get("publicationTypes") or []),
        citations=r.get("citationCount"), influential=r.get("influentialCitationCount"),
        is_oa=r.get("isOpenAccess"), oa_url=pdf.get("url"), abstract=r.get("abstract"),
        pass_name=pass_name, journal=(r.get("journal") or {}).get("name"),
        fieldsOfStudy=(r.get("fieldsOfStudy") or []),
    )


def fetch_core(a):
    """Grey literature and repository OA copies. `fullText` (80-180k chars per record) is dropped
    here and never reaches the agent; only `hasFullText` survives."""
    key = os.environ.get("CORE_API_KEY", "")
    if not key:
        return envelope("core", "unavailable", note="no CORE_API_KEY in env"), 2
    url = CORE + "?" + urllib.parse.urlencode({"q": a.query, "limit": a.limit})
    j, h = request(url, headers={"Authorization": "Bearer " + key}, pause=3.0)
    if j is None:
        return envelope("core", "unavailable", note="search/works did not answer after retries"), 2
    rows = [core_record(r) for r in (j.get("results") or [])]
    note = ""
    if a.year_from:  # CORE's year syntax is brittle — filter deterministically here instead
        before = len(rows)
        rows = [r for r in rows if not r.get("year") or int(r["year"]) >= a.year_from]
        note = "year filter applied client-side (%d → %d)" % (before, len(rows))
    papers, passes = merge_passes([("keywords", rows)], a.limit)
    passes[0]["requested"] = a.limit
    return envelope("core", "ok" if papers else "empty", papers, first_year_free_int(j.get("totalHits")),
                    passes, remaining=h.get("x-ratelimit-remaining"), note=note), 0


def fetch_clinicaltrials(a):
    """Registry records, not peer-reviewed papers: conditions/interventions/outcome become a short
    abstract-like string, enrollment becomes sampleN, the NCT id becomes externalId."""
    params = {"query.term": a.query, "pageSize": min(a.limit, 1000), "format": "json",
              "countTotal": "true", "sort": "LastUpdatePostDate:desc"}
    j, _ = request(CTGOV + "?" + urllib.parse.urlencode(params), pause=3.0)
    if j is None:
        return envelope("clinicaltrials", "unavailable", note="api/v2/studies did not answer after retries"), 2
    rows = [ct_record(s) for s in (j.get("studies") or [])]
    note = ""
    if a.year_from:
        before = len(rows)
        rows = [r for r in rows if not r.get("year") or int(r["year"]) >= a.year_from]
        note = "year filter applied client-side (%d → %d)" % (before, len(rows))
    papers, passes = merge_passes([("term", rows)], a.limit)
    passes[0]["requested"] = min(a.limit, 1000)
    return envelope("clinicaltrials", "ok" if papers else "empty", papers,
                    first_year_free_int(j.get("totalCount")), passes, note=note), 0


def ct_record(study, pass_name="term"):
    ps = (study or {}).get("protocolSection") or {}
    ident = ps.get("identificationModule") or {}
    st = ps.get("statusModule") or {}
    design = ps.get("designModule") or {}
    conds = (ps.get("conditionsModule") or {}).get("conditions") or []
    intrs = [i.get("name") for i in ((ps.get("armsInterventionsModule") or {}).get("interventions") or [])]
    outcomes = [o.get("measure") for o in ((ps.get("outcomesModule") or {}).get("primaryOutcomes") or [])]
    refs = (ps.get("referencesModule") or {}).get("references") or []
    pmid = next((r.get("pmid") for r in refs if (r.get("type") or "").upper() == "RESULT" and r.get("pmid")), None)
    year = first_year((st.get("primaryCompletionDateStruct") or {}).get("date")) \
        or first_year((st.get("completionDateStruct") or {}).get("date")) \
        or first_year((st.get("startDateStruct") or {}).get("date"))
    phases = design.get("phases") or []
    summary = "Conditions: %s. Interventions: %s. Primary outcome: %s. Status: %s." % (
        ", ".join([c for c in conds if c]) or "—",
        ", ".join([i for i in intrs if i][:6]) or "—",
        "; ".join([o for o in outcomes if o][:3]) or "—",
        st.get("overallStatus") or "—")
    return paper(
        title=ident.get("briefTitle"), external_id=ident.get("nctId"), pmid=pmid, year=year,
        pub_types=[design.get("studyType")] + phases, is_oa=False, abstract=summary, pass_name=pass_name,
        status=st.get("overallStatus"), phase=(", ".join(phases) or None),
        sampleN=((design.get("enrollmentInfo") or {}).get("count")),
        resultsPosted=bool(st.get("resultsFirstPostDateStruct")),
        # `year` is the primary completion date — for a recruiting trial it lies in the future,
        # so the start year is kept beside it instead of being lost
        startYear=first_year((st.get("startDateStruct") or {}).get("date")),
    )


SOURCES = {
    "pubmed": fetch_pubmed, "europepmc": fetch_europepmc, "openalex": fetch_openalex,
    "s2": fetch_s2, "core": fetch_core, "clinicaltrials": fetch_clinicaltrials,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", choices=sorted(SOURCES))
    ap.add_argument("--query", required=True, help="native query string for this source, as the protocol writes it")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--year-from", type=int, default=None, dest="year_from")
    ap.add_argument("--preprints", action="store_true", help="Europe PMC only: an extra SRC:PPR pass on top of LIMIT")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    out, code = SOURCES[a.source](a)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        summary = dict((k, v) for k, v in out.items() if k != "papers")
        summary["papers"] = len(out["papers"])
        summary["withAbstract"] = sum(1 for p in out["papers"] if p.get("abstract"))
        summary["withDoi"] = sum(1 for p in out["papers"] if p.get("doi"))
        summary["out"] = a.out
        print(redact(json.dumps(summary, ensure_ascii=False)))
    else:
        print(redact(text))
    sys.exit(code)


if __name__ == "__main__":
    main()
