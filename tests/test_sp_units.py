"""Unit tests of the pure helpers of workflows/search-paper-core.js (ranked cut, subquestion
coverage, grey literature, coverage telemetry) plus the corpus-cap regression.

The JS harness does the asserting — this wrapper only runs it and surfaces the output, the same
shape as test_sp_dryrun.py. No network, no model calls.
"""

import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "sp_units.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_pure_helpers_hold():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "UNITS OK" in r.stdout, r.stdout
    # the two findings the release is about, named so a failure says which one broke
    assert "ok   rankedCut: все 5 статей узкой подтемы выжили" in r.stdout, r.stdout
    assert "ok   capHitSnowball: потолок во время snowball взводит флаг" in r.stdout, r.stdout
