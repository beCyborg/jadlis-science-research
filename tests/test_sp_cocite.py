"""scripts/cocite.py: the co-citation prefilter must stay runnable by the system Python and
stay wired into the workflow. Network is never touched here.
"""

import ast
import importlib.util
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cocite.py"
CORE_SRC = (ROOT / "workflows" / "search-paper-core.js").read_text(encoding="utf-8")


def load():
    spec = importlib.util.spec_from_file_location("sp_cocite", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_parses_as_python_39():
    # Agents run it with the system `python3` (3.9.6 on macOS CommandLineTools): no match/case,
    # no `X | Y` annotations, no parenthesized context managers.
    ast.parse(SCRIPT.read_text(encoding="utf-8"), feature_version=(3, 9))


def test_chase_script_parses_as_python_39_and_is_wired():
    chase = ROOT / "scripts" / "chase.py"
    ast.parse(chase.read_text(encoding="utf-8"), feature_version=(3, 9))
    assert "scripts/chase.py" in CORE_SRC
    # chased papers must carry the 'sn' source tag, not their per-paper prefix
    assert "_src: 'sn'" in CORE_SRC


def test_norm_doi_strips_resolver_and_case():
    m = load()
    assert m.norm_doi("https://doi.org/10.1093/SLEEP/33.12.1605") == "10.1093/sleep/33.12.1605"
    assert m.norm_doi("http://dx.doi.org/10.1/x") == "10.1/x"
    assert m.norm_doi(None) == ""


def test_workflow_calls_the_script_and_can_switch_it_off():
    assert "scripts/cocite.py" in CORE_SRC
    assert re.search(r"const COCITE = A\.cocite !== false", CORE_SRC)
    # the step must feed synthesis, otherwise co-cited papers reach the report as bare DOIs
    assert "cocite.md" in CORE_SRC.split("const synthFiles")[1].split("\n")[0]


def test_cocite_prefix_does_not_collide_with_a_source_prefix():
    prefixes = re.findall(r"prefix:\s*'([^']+)'", CORE_SRC.split("const ALL_SOURCES")[1].split("\n}")[0])
    assert "cc" not in prefixes, prefixes
