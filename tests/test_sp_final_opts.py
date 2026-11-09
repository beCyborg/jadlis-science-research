"""Final-agent routing of search-paper-core.js (2.4.0): args.finalOpts from the personal
~/.claude/skills/_shared/final-agent.json moves synth + critic to that model; without it the
defaults stay (Opus 5.5 xhigh); every retry after a null answer runs on Opus 5.5. Offline."""

import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "sp_final_opts.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_final_opts_routing_offline():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FINAL_OPTS=ok" in r.stdout, r.stdout
