"""Args guard of workflows/search-paper-core.js: no args, unparsable args (curly quotes) and a
relative workDir throw before the first agent; full args and dryRun:true pass the guard.

The JS harness does the asserting — this wrapper only runs it and surfaces the output, the same
shape as test_sp_dryrun.py. No network, no model calls.
"""

import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "sp_args_guard.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_broken_args_fail_before_any_agent():
    r = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "GUARD OK" in r.stdout, r.stdout
    for case in ("no-args", "curly-quotes", "relative-workdir", "missing-and-empty", "not-an-object",
                 "full-args-pass", "dryrun-defaults"):
        assert f"ok   guard:{case}" in r.stdout, r.stdout
