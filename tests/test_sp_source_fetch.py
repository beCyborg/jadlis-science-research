"""scripts/source-fetch.py: the fan-out fetcher must stay runnable by the system Python, stay
wired into the protocols, and keep its normalization honest. Network is never touched here —
every check feeds the pure functions an inline fixture.
"""

import argparse
import ast
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "source-fetch.py"
PROTOCOLS = ROOT / "skills" / "science-research" / "protocols"
CORE_SRC = (ROOT / "workflows" / "search-paper-core.js").read_text(encoding="utf-8")


def load():
    spec = importlib.util.spec_from_file_location("sp_source_fetch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_parses_as_python_39():
    # Agents run it with the system `python3` (3.9.6 on macOS CommandLineTools): no match/case,
    # no `X | Y` annotations, no parenthesized context managers.
    ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 9))


def test_every_api_source_has_a_subcommand():
    m = load()
    assert set(m.SOURCES) == {"pubmed", "europepmc", "openalex", "s2", "core", "clinicaltrials"}


def test_script_first_section_is_in_every_api_protocol():
    # The whole point of the script is that the agent starts there; a protocol that forgot the
    # section sends its agent back to hand-written curl and to 20-50 turns.
    files = {
        "pubmed-protocol.md": "pubmed", "europe-pmc-protocol.md": "europepmc",
        "openalex-protocol.md": "openalex", "s2-protocol.md": "s2",
        "core-protocol.md": "core", "clinicaltrials-protocol.md": "clinicaltrials",
    }
    for name, sub in files.items():
        text = (PROTOCOLS / name).read_text(encoding="utf-8")
        assert "Primary: скрипт" in text, name
        assert "scripts/source-fetch.py" in text, name
        assert ('source-fetch.py" %s ' % sub) in text, (name, sub)  # the right subcommand, quoted path
        assert "apiStatus=unavailable" in text, name


def test_mcp_only_protocols_carry_a_turn_budget_instead():
    for name in ("cochrane-guidelines-protocol.md", "web-experts-protocol.md",
                 "epistemonikos-protocol.md"):
        text = (PROTOCOLS / name).read_text(encoding="utf-8")
        assert "Бюджет ходов" in text, name
        assert "scripts/source-fetch.py" not in text, name


def test_workflow_points_the_agent_at_the_script_section():
    assert "Primary: скрипт" in CORE_SRC


def test_norm_doi_strips_resolver_and_case():
    m = load()
    assert m.norm_doi("https://doi.org/10.1093/SLEEP/33.12.1605") == "10.1093/sleep/33.12.1605"
    assert m.norm_doi("http://dx.doi.org/10.1/X") == "10.1/x"
    assert m.norm_doi("  10.1/Y  ") == "10.1/y"
    # a missing identifier is null, never an empty string that later reads as "we have a DOI"
    assert m.norm_doi(None) is None
    assert m.norm_doi("") is None


def test_abstract_reconstruction_from_inverted_index():
    m = load()
    inv = {"Melatonin": [0], "advances": [1], "the": [2, 5], "circadian": [3], "phase": [4], "in": [6],
           "DSWPD": [7]}
    assert m.abstract_from_inverted_index(inv) == "Melatonin advances the circadian phase the in DSWPD"
    assert m.abstract_from_inverted_index(None) is None
    assert m.abstract_from_inverted_index({}) is None


def test_abstract_is_capped_and_never_exceeds_the_cap():
    m = load()
    long_inv = dict(("w%d" % i, [i]) for i in range(1000))
    out = m.abstract_from_inverted_index(long_inv)
    assert len(out) <= m.ABSTRACT_CAP and out.endswith("…")
    assert m.cap_abstract("  a\n\n b  ") == "a b"
    assert m.cap_abstract("   ") is None


PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation>
   <PMID Version="1">20430886</PMID>
   <Article>
    <Journal><Title>Sleep</Title><JournalIssue><PubDate><Year>2010</Year><Month>Dec</Month></PubDate></JournalIssue></Journal>
    <ArticleTitle>Melatonin for delayed sleep phase disorder</ArticleTitle>
    <Abstract>
     <AbstractText Label="METHODS">A randomized trial.</AbstractText>
     <AbstractText Label="RESULTS">Sleep onset advanced by 30 min.</AbstractText>
    </Abstract>
    <PublicationTypeList>
     <PublicationType>Randomized Controlled Trial</PublicationType>
     <PublicationType>Journal Article</PublicationType>
    </PublicationTypeList>
   </Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList>
   <ArticleId IdType="pubmed">20430886</ArticleId>
   <ArticleId IdType="doi">10.1093/SLEEP/33.12.1605</ArticleId>
  </ArticleIdList></PubmedData>
 </PubmedArticle>
 <PubmedBookArticle>
  <BookDocument>
   <PMID Version="1">31841296</PMID>
   <Book><BookTitle book="endotext">Endotext</BookTitle><PubDate><Year>2000</Year></PubDate></Book>
   <ArticleTitle>Physiology of the Pineal Gland</ArticleTitle>
   <Abstract><AbstractText>Melatonin is secreted at night.</AbstractText></Abstract>
  </BookDocument>
 </PubmedBookArticle>
</PubmedArticleSet>"""


def test_pubmed_efetch_xml_becomes_a_record():
    m = load()
    recs = m.parse_pubmed_xml(PUBMED_XML)
    assert len(recs) == 2
    art = recs[0]
    assert art["pmid"] == "20430886"
    assert art["title"] == "Melatonin for delayed sleep phase disorder"
    assert art["doi"] == "10.1093/sleep/33.12.1605"  # normalized, not the raw uppercase form
    assert art["year"] == 2010
    assert "Randomized Controlled Trial" in art["pubTypes"]
    assert art["abstract"] == "Methods: A randomized trial. Results: Sleep onset advanced by 30 min."
    assert art["journal"] == "Sleep"
    # a book chapter (Endotext/StatPearls) is a PubmedBookArticle — it used to come back empty
    book = recs[1]
    assert book["pmid"] == "31841296" and book["title"] == "Physiology of the Pineal Gland"
    assert book["year"] == 2000 and book["abstract"] == "Melatonin is secreted at night."


def test_pubmed_parser_survives_garbage():
    m = load()
    assert m.parse_pubmed_xml("<html>502 Bad Gateway</html>") == []
    assert m.parse_pubmed_xml("") == []


def test_europepmc_failure_criterion_is_the_missing_hitcount():
    m = load()
    # 21.09.2026: HTTP 200 with a body of {"version":"6.9"} all day — no hitCount, no resultList
    assert m.epmc_status({"version": "6.9"}) == "unavailable"
    assert m.epmc_status(None) == "unavailable"
    assert m.epmc_status("<html/>") == "unavailable"
    # hitCount: 0 is a legitimate empty result, NOT a failure — it must not trigger the fallback
    assert m.epmc_status({"hitCount": 0, "resultList": {"result": []}}) == "empty"
    assert m.epmc_status({"hitCount": 208, "resultList": {"result": [{"title": "x"}]}}) == "ok"


def test_core_record_drops_fulltext():
    m = load()
    raw = {
        "id": 45972049, "title": "Delayed sleep phase syndrome and melatonin treatment",
        "doi": "https://doi.org/10.1234/ABC", "yearPublished": 2014, "documentType": "thesis",
        "abstract": "A meta-analysis of melatonin.", "downloadUrl": "https://core.ac.uk/download/1.pdf",
        "dataProviders": [{"name": "Munin - Open Research Archive"}],
        "fullText": "x" * 120000,  # 80-180k chars per record — it must never reach the agent
    }
    rec = m.core_record(raw)
    assert "fullText" not in rec
    assert m.ABSTRACT_CAP >= len(rec["abstract"] or "")
    assert rec["hasFullText"] is True
    assert rec["doi"] == "10.1234/abc"
    assert rec["externalId"] == "45972049" and rec["year"] == 2014
    assert rec["oaUrl"] == "https://core.ac.uk/download/1.pdf" and rec["isOA"] is True
    assert rec["repository"] == "Munin - Open Research Archive"
    assert len(repr(rec)) < 5000
    # CORE gives no citation metrics — they stay null instead of becoming 0
    assert rec["citations"] is None and rec["fwci"] is None
    assert m.core_record({})["hasFullText"] is False


def test_clinicaltrials_record_normalization():
    m = load()
    study = {"protocolSection": {
        "identificationModule": {"nctId": "NCT01234567", "briefTitle": "Melatonin in DSWPD"},
        "statusModule": {"overallStatus": "COMPLETED",
                         "startDateStruct": {"date": "2018-03"},
                         "primaryCompletionDateStruct": {"date": "2020-06-15"},
                         "resultsFirstPostDateStruct": {"date": "2021-01-01"}},
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE3"],
                         "enrollmentInfo": {"count": 116}},
        "conditionsModule": {"conditions": ["Delayed Sleep Phase Disorder"]},
        "armsInterventionsModule": {"interventions": [{"name": "Melatonin 0.5 mg"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "DLMO shift"}]},
        "referencesModule": {"references": [{"pmid": "33333333", "type": "RESULT"},
                                            {"pmid": "44444444", "type": "BACKGROUND"}]},
    }}
    rec = m.ct_record(study)
    assert rec["externalId"] == "NCT01234567"
    assert rec["year"] == 2020 and rec["startYear"] == 2018  # year = primary completion date
    assert rec["sampleN"] == 116 and rec["phase"] == "PHASE3"
    assert rec["status"] == "COMPLETED" and rec["resultsPosted"] is True
    assert rec["pmid"] == "33333333"  # only the reference typed RESULT
    assert rec["doi"] is None  # a registry record has no DOI — it is never invented
    assert "Delayed Sleep Phase Disorder" in rec["abstract"] and "Melatonin 0.5 mg" in rec["abstract"]
    assert m.ct_record({})["externalId"] is None


def test_merge_passes_dedupes_and_keeps_preprints_on_top_of_the_limit():
    m = load()
    a = m.paper("A", doi="10.1/a", pass_name="cited")
    b = m.paper("B", doi="10.1/b", pass_name="cited")
    dup = m.paper("A again", doi="https://doi.org/10.1/A", pass_name="recent")
    pre = m.paper("P", doi="10.1/p", pass_name="preprint", preprint=True)
    papers, passes = m.merge_passes([("cited", [a, b]), ("recent", [dup])], 2, [pre])
    assert [p["doi"] for p in papers] == ["10.1/a", "10.1/b", "10.1/p"]  # preprint rides on top
    assert passes[1]["new"] == 0  # the recent pass brought only a duplicate


def test_envelope_marks_truncation_from_the_api_hit_count():
    m = load()
    assert m.envelope("pubmed", "ok", [{"title": "x"}], total=207)["truncated"] is True
    assert m.envelope("pubmed", "ok", [{"title": "x"}], total=1)["truncated"] is False
    assert m.envelope("pubmed", "empty", [], total=0)["truncated"] is False


def test_pubmed_quotas_are_half_quarter_quarter():
    m = load()
    # evidence : observational : general = 1/2 : 1/4 : 1/4 — the observational pass exists because
    # the evidence filter used to take 2/3 of the slots and cohorts fought for the remaining third
    assert m.pubmed_quotas(40) == (20, 10, 10)
    assert sum(m.pubmed_quotas(40)) == 40
    assert sum(m.pubmed_quotas(30)) == 30
    # never zero, whatever the limit
    assert all(q >= 1 for q in m.pubmed_quotas(1))
    assert all(q >= 1 for q in m.pubmed_quotas(4))


def test_pubmed_plan_carries_three_passes_with_the_right_filters():
    m = load()
    src = SCRIPT.read_text(encoding="utf-8")
    assert "observational study[pt]" in m.OBS_FILTER and "cohort studies[mh]" in m.OBS_FILTER
    assert "case-control studies[mh]" in m.OBS_FILTER and "cross-sectional studies[mh]" in m.OBS_FILTER
    body = src.split("def fetch_pubmed")[1].split("\ndef ")[0]
    assert '("evidence"' in body and '("observational"' in body and '("general"' in body
    assert "pubmed_quotas(a.limit)" in body


def test_per_query_limit_has_a_floor_of_eight():
    m = load()
    assert m.per_query_limit(40, 1) == 40      # one query → the whole budget, as before
    assert m.per_query_limit(40, 4) == 10
    assert m.per_query_limit(40, 7) == 8       # floor: below 8 a narrow query returns noise only
    assert m.per_query_limit(5, 3) == 8


def test_load_queries_keeps_order_and_dedupes():
    m = load()
    assert m.load_queries(["a", "a", "b"], None) == ["a", "b"]
    assert m.load_queries(["  ", "x"], None) == ["x"]
    assert m.load_queries([], None) == []


def test_load_queries_reads_both_file_shapes(tmp_path):
    m = load()
    plain = tmp_path / "q1.json"
    plain.write_text('["main", "extra"]', encoding="utf-8")
    assert m.load_queries([], str(plain)) == ["main", "extra"]
    objs = tmp_path / "q2.json"
    objs.write_text('[{"query": "main", "key": "pubmed:main"}, {"query": "sub"}]', encoding="utf-8")
    assert m.load_queries([], str(objs)) == ["main", "sub"]
    # the --query ones come first: the source's MAIN query must keep its ranking after dedup
    assert m.load_queries(["main"], str(objs)) == ["main", "sub"]


def test_run_queries_merges_dedupes_and_records_per_query_numbers(monkeypatch):
    m = load()
    calls = []

    def fake(a):
        calls.append((a.query, a.limit))
        if a.query == "dead":
            return m.envelope("fake", "unavailable", note="down"), 2
        rows = [m.paper("A", doi="10.1/a"), m.paper("B", doi="10.1/" + a.query)]
        return m.envelope("fake", "ok", rows, total=100 + len(a.query)), 0

    monkeypatch.setitem(m.SOURCES, "pubmed", fake)
    args = argparse.Namespace(query="main", limit=40, year_from=None, preprints=False, out=None)
    out, code = m.run_queries("pubmed", args, ["main", "sub", "dead"])
    assert code == 0
    assert [q[1] for q in calls] == [13, 13, 13]           # max(8, 40 // 3)
    # the shared paper 10.1/a is kept once, in the order the main query returned it
    assert [p["doi"] for p in out["papers"]] == ["10.1/a", "10.1/main", "10.1/sub"]
    assert [p["queryIndex"] for p in out["papers"]] == [0, 0, 1]
    per = {q["index"]: q for q in out["queries"]}
    assert per[0]["kept"] == 2 and per[1]["kept"] == 1
    assert per[2]["apiStatus"] == "unavailable" and per[2]["kept"] == 0
    assert out["total"] == 104                             # total belongs to the MAIN query
    assert out["apiStatus"] == "ok"                        # one dead extra query never sinks the run


def test_run_queries_reports_unavailable_only_when_every_query_failed(monkeypatch):
    m = load()
    monkeypatch.setitem(m.SOURCES, "s2", lambda a: (m.envelope("s2", "unavailable", note="down"), 2))
    args = argparse.Namespace(query="a", limit=30, year_from=None, preprints=False, out=None)
    out, code = m.run_queries("s2", args, ["a", "b"])
    assert code == 2 and out["apiStatus"] == "unavailable"
    assert len(out["queries"]) == 2


def test_single_query_behaves_exactly_as_before(monkeypatch):
    m = load()
    seen = []

    def fake(a):
        seen.append(a.limit)
        return m.envelope("europe-pmc", "ok", [m.paper("A", doi="10.1/a")], total=7), 0

    monkeypatch.setitem(m.SOURCES, "europepmc", fake)
    args = argparse.Namespace(query="q", limit=40, year_from=None, preprints=False, out=None)
    out, code = m.run_queries("europepmc", args, ["q"])
    assert seen == [40] and code == 0
    assert out["source"] == "europe-pmc"   # the fetcher's own label survives, not the subcommand
    assert out["total"] == 7 and len(out["papers"]) == 1


def test_keys_are_never_printed():
    m = load()
    assert "secret" not in m.redact("https://api.example.com/x?api_key=secret123&q=1")
    assert "***" in m.redact("api_key=secret123")
    assert "***" in m.redact("HTTP Error 401: token=abcdef")
