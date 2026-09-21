"""Registry invariants of workflows/search-paper-core.js, checked as text.

The workflow is never executed here: it is an ESM body meant for the Workflow tool, so the
cheapest guard that still catches real breakage is a parse of the source.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "workflows" / "search-paper-core.js"
SRC = CORE.read_text(encoding="utf-8")

# `  key: { source: 'X', prefix: 'pm', protocol: PROTO('pubmed-protocol.md'), file: 'y.md', … }`
SOURCE_ROW = re.compile(
    r"^\s*(?P<key>\w+)\s*:\s*\{[^}]*?prefix:\s*'(?P<prefix>[^']+)'"
    r"[^}]*?PROTO\('(?P<protocol>[^']+)'\)",
    re.M,
)


def all_sources():
    block = re.search(r"const ALL_SOURCES = \{(.*?)\n\}", SRC, re.S)
    assert block, "ALL_SOURCES block not found"
    rows = {m.group("key"): m.groupdict() for m in SOURCE_ROW.finditer(block.group(1))}
    assert rows, "no source rows parsed out of ALL_SOURCES"
    return rows


def test_every_source_has_a_protocol_file():
    missing = [
        (key, row["protocol"])
        for key, row in all_sources().items()
        if not (ROOT / "skills" / "science-research" / "protocols" / row["protocol"]).is_file()
    ]
    assert not missing, missing


def test_prefixes_are_unique():
    # A prefix is the citation anchor in the report ([pm1], [cr3]) — a collision silently
    # merges two sources in the Evidence Table.
    owner = {}
    dupes = []
    for key, row in all_sources().items():
        prefix = row["prefix"]
        if prefix in owner:
            dupes.append((prefix, owner[prefix], key))
        else:
            owner[prefix] = key
    assert not dupes, dupes


def test_every_source_is_selectable_by_default():
    base = re.search(r"const base = \[(.*?)\]", SRC, re.S)
    assert base, "defaultSources() base array not found"
    listed = set(re.findall(r"'([^']+)'", base.group(1)))
    assert listed == set(all_sources()), (listed ^ set(all_sources()))


def test_search_plan_enumerates_every_source():
    # The query-builder must emit one query string per source, or the fan-out agent silently
    # falls back to the raw EN query.
    queries = re.search(r"queries:\s*\{(.*?)\n    \},", SRC, re.S)
    assert queries, "SEARCH_PLAN.queries block not found"
    body = queries.group(1)
    props = set(re.findall(r"^\s{8}(\w+):\s*\{", body, re.M))
    required = re.search(r"required:\s*\[([^\]]*)\]", body, re.S)
    assert required, "SEARCH_PLAN.queries required[] not found"
    req = set(re.findall(r"'([^']+)'", required.group(1)))
    sources = set(all_sources())
    assert props == sources, (props ^ sources)
    assert req == sources, (req ^ sources)


def test_meta_block_is_a_pure_literal():
    # `meta` is read without executing the script: a template literal or a variable in it
    # surfaces to the user as raw `${...}` in the phase list.
    meta = re.search(r"export const meta = \{(.*?)\n\}", SRC, re.S)
    assert meta, "meta block not found"
    body = meta.group(1)
    assert "`" not in body, "meta contains a template literal"
    assert "${" not in body, "meta contains an interpolation"
    unquoted = [
        m.group(0) for m in re.finditer(r"\b(?:name|description|title|detail)\s*:\s*(.)", body)
        if m.group(1) not in "'\""
    ]
    assert not unquoted, unquoted


def test_caps_are_arg_overridable():
    # A recall measurement runs old and new caps on the same code — the caps must come from args.
    for name in ("perSourceTop", "paperCap", "fulltextCap"):
        assert re.search(r"capArg\(A\.%s\b" % name, SRC), name
