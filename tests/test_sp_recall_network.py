"""Recall regression on the four papers the 2026-09 nicotine run lost (network, off by default).

The run «Никотиновые пакетики для фокуса» (286 papers) missed work that two outside reports found
in minutes. Every one of them WAS in the PubMed result set — it sat below the cut because the
source got one query for a twelve-subtopic question and two thirds of the slots went to the
evidence-type filter. This test runs the fixed script the way the workflow now calls it — the
subquestion queries of that run, all in ONE invocation — and asserts the four PMIDs come back.

Observed 2026-09-21 (limit 40, four queries → 10 per query, passes 6/2/2): 22 unique papers, all
four PMIDs present at merged ranks 0, 5, 15, 20 — per query kept 2, 5, 10, 5. Two of them are
close to their pass quota (Carlsson is 2nd in the general pass, Camfield 4th in the evidence pass),
so a smaller `--limit` or more queries in one call can push them out again: that is the signal this
test exists for, not a flake.

Marked `network` and excluded by pytest.ini's default `-m "not network"`; CI never runs it.
Run it by hand after touching the passes or the multi-query plumbing:

    uv run --with pytest pytest tests/test_sp_recall_network.py -m network -q -s
"""

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "source-fetch.py"

# subquestion → (query, PMID that must come back)
CASES = [
    ("сперма",
     '("nicotine pouch"[tiab] OR snus[tiab] OR "smokeless tobacco"[tiab]) '
     'AND (sperm[tiab] OR spermatozoa[tiab] OR semen[tiab])',
     "35642735"),    # Kimblad 2022 — snus and sperm counts
    ("диабет 2 типа",
     '(snus[tiab] OR "smokeless tobacco"[tiab]) AND ("type 2 diabetes"[tiab] OR "diabetes mellitus"[tiab]) '
     'AND (cohort[tiab] OR prospective[tiab])',
     "28164394"),    # Carlsson 2017 — snus and type 2 diabetes, five pooled cohorts
    ("когниция",
     'nicotine[tiab] AND (cognitive[tiab] OR cognition[tiab]) '
     'AND ("systematic review"[tiab] OR meta-analysis[tiab])',
     "32547048"),    # Pasetes 2020 — nicotine, cognition and industry affiliation
    ("кофеин и L-теанин",
     '(theanine[tiab] OR "l-theanine"[tiab]) AND caffeine[tiab] '
     'AND ("systematic review"[tiab] OR meta-analysis[tiab])',
     "24946991"),    # Camfield 2014 — L-theanine + caffeine, SR and meta-analysis
]


@pytest.mark.network
def test_lost_papers_come_back_with_subquestion_queries(tmp_path):
    out = tmp_path / "pubmed.json"
    cmd = [sys.executable, str(SCRIPT), "pubmed", "--limit", "40", "--out", str(out)]
    for _label, query, _pmid in CASES:
        cmd += ["--query", query]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    papers = data["papers"]
    rank = {}
    for i, p in enumerate(papers):
        if p.get("pmid") and p["pmid"] not in rank:
            rank[p["pmid"]] = i
    print("\npapers=%d  per-query=%s" % (
        len(papers), [(q["index"], q["total"], q["kept"]) for q in data["queries"]]))
    for label, _query, pmid in CASES:
        print("  %-18s PMID %s → %s" % (label, pmid, ("rank %d" % rank[pmid]) if pmid in rank else "MISSING"))
    missing = [pmid for _l, _q, pmid in CASES if pmid not in rank]
    assert not missing, "PMIDs missing from the merged result: %s" % missing
