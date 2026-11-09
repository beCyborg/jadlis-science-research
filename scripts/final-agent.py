#!/usr/bin/env python3
"""final-agent.py — read the OPTIONAL personal override for the last agent of a pipeline.

Contract: ~/.claude/skills/_shared/final-agent.json = {"model": "<claude-…>", "effort": "<level>"}.
The file is personal (it is never shipped with a plugin). The skill runs this script, passes
`finalOpts` into the workflow args (or the model/effort into a headless call) and says in one line
which model the final agent got.

Prints ONE JSON line:
  {"finalOpts": {"model": "...", "effort": "..."}, "source": "<path>"}            — the file is valid
  {"finalOpts": null, "reason": "no file|unreadable JSON|bad model|bad effort"}  — plugin default
Any problem → finalOpts null → the plugin keeps its built-in default. Exit code is always 0.
Override the path with FINAL_AGENT_FILE (tests).
"""
import json
import os
import re

PATH = os.environ.get("FINAL_AGENT_FILE") or os.path.expanduser("~/.claude/skills/_shared/final-agent.json")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def main():
    if not os.path.isfile(PATH):
        return {"finalOpts": None, "reason": "no file"}
    try:
        with open(PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {"finalOpts": None, "reason": "unreadable JSON"}
    if not isinstance(data, dict):
        return {"finalOpts": None, "reason": "unreadable JSON"}
    model, effort = data.get("model"), data.get("effort")
    if not isinstance(model, str) or not re.fullmatch(r"claude-[a-z0-9-]+", model):
        return {"finalOpts": None, "reason": "bad model"}
    if effort not in EFFORTS:
        return {"finalOpts": None, "reason": "bad effort"}
    return {"finalOpts": {"model": model, "effort": effort}, "source": PATH}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
