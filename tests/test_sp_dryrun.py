"""Offline run of workflows/search-paper-core.js with stubbed agent/parallel/pipeline.

Proves that every prompt builder renders (no ReferenceError, no unresolved template, no literal
"undefined") and that each stage — including the script-driven cocite and chase steps — is reached.
No network, no model calls.
"""

import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "sp_dryrun.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_prompt_renders_offline():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RUN OK status=ok" in r.stdout, r.stdout
    assert "BROKEN_TEMPLATES=none" in r.stdout, r.stdout
    # the prompt contract: subquestion queries reach the source agent in ONE script call, the
    # synthesizer is pointed at plain-language.md, the fix agent stops stamping [AR-fix]
    assert "PROMPT_CONTRACT=ok" in r.stdout, r.stdout
    for stage in ("query", "core", "dedup", "cocite", "chase", "enrich", "fulltext", "synth", "adversarial", "fix"):
        assert f"  {stage}: rendered" in r.stdout, r.stdout
