import pathlib
import re

BLOCKED = re.compile(r"^(REPORT|SUMMARY|FINDINGS|ANALYSIS).*\.md$", re.I)
WORKFLOWS = pathlib.Path(__file__).resolve().parent.parent / "workflows"


def workdir_names():
    for js in WORKFLOWS.glob("*.js"):
        for m in re.finditer(r"\$\{WORK_DIR\}/([A-Za-z0-9_./{}$-]+)", js.read_text()):
            yield js.name, m.group(1).rsplit("/", 1)[-1]


def test_workdir_files_are_writable_by_subagents():
    # Claude Code 2.1.276+ refuses subagent Write to these basenames (errorCode 5)
    names = list(workdir_names())
    assert names
    bad = [(js, n) for js, n in names if BLOCKED.match(n)]
    assert not bad, bad
