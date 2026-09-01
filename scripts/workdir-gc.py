#!/usr/bin/env python3
"""Retention GC for research skill work directories in the Obsidian vault.

Scans <root>/.full-research/* and <root>/.search-paper/* (first-level dirs only)
and classifies each work dir as KEEP or DELETE based on:
  * whether a vault note under <root>/Знания/ references it via a
    `work_dir:` frontmatter key (matched by directory basename),
  * its age (max of dir mtime and newest top-level file mtime),
  * protection rules (--protect, mtime < 24h, presence of a `.keep` file).

Dry-run by default in spirit: real deletion requires --yes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

SCAN_SUBDIRS = (".full-research", ".search-paper")
NOTES_SUBDIR = "Знания"
FRONTMATTER_SCAN_LINES = 60
PROTECT_MARKER = ".keep"
FRESH_SECONDS = 24 * 3600

# work_dir: "path" | work_dir: 'path' | work_dir: path
WORK_DIR_RE = re.compile(r'^\s*work_dir\s*:\s*(.+?)\s*$')


def unquote(value: str) -> str:
    """Strip matching surrounding quotes and trailing YAML comments-ish noise."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def scan_references(notes_root: str) -> dict[str, list[str]]:
    """Map work dir basename -> list of note paths referencing it.

    One pass over every .md file under notes_root; only the first
    FRONTMATTER_SCAN_LINES lines of each file are inspected. Symlinks skipped.
    """
    refs: dict[str, list[str]] = {}
    if not os.path.isdir(notes_root):
        return refs

    for dirpath, dirnames, filenames in os.walk(notes_root, followlinks=False):
        # do not descend into symlinked directories
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh):
                        if i >= FRONTMATTER_SCAN_LINES:
                            break
                        m = WORK_DIR_RE.match(line)
                        if not m:
                            continue
                        raw = unquote(m.group(1))
                        if not raw:
                            continue
                        base = os.path.basename(raw.rstrip("/"))
                        if base:
                            refs.setdefault(base, []).append(path)
            except OSError as exc:
                print(f"warn: cannot read {path}: {exc}", file=sys.stderr)
    return refs


def dir_age_seconds(path: str, now: float) -> float:
    """max(dir mtime, newest top-level file mtime) -> age in seconds.

    Non-recursive on purpose: recursing over every work dir is expensive.
    """
    newest = 0.0
    try:
        newest = os.lstat(path).st_mtime
    except OSError:
        pass
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if mtime > newest:
                    newest = mtime
    except OSError as exc:
        print(f"warn: cannot scan {path}: {exc}", file=sys.stderr)
    return max(0.0, now - newest)


def dir_size_bytes(path: str) -> int:
    """Recursive sum of st_size for regular files (du-compatible enough)."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            fpath = os.path.join(dirpath, name)
            try:
                st = os.lstat(fpath)
            except OSError:
                continue
            if os.path.islink(fpath):
                continue
            total += st.st_size
    return total


def human_size(num_bytes: int) -> str:
    mib = num_bytes / (1024 * 1024)
    if mib >= 1024:
        return f"{mib / 1024:.2f}G"
    return f"{mib:.1f}M"


def collect(root: str, protect: set[str], keep_days: int, orphan_days: int) -> list[dict]:
    now = time.time()
    refs = scan_references(os.path.join(root, NOTES_SUBDIR))
    entries: list[dict] = []

    for sub in SCAN_SUBDIRS:
        base_dir = os.path.join(root, sub)
        if not os.path.isdir(base_dir):
            continue
        try:
            names = sorted(os.listdir(base_dir))
        except OSError as exc:
            print(f"warn: cannot list {base_dir}: {exc}", file=sys.stderr)
            continue
        for name in names:
            path = os.path.join(base_dir, name)
            if os.path.islink(path) or not os.path.isdir(path):
                continue

            age_s = dir_age_seconds(path, now)
            age_days = age_s / 86400.0
            referenced_by = refs.get(name, [])
            referenced = bool(referenced_by)

            protected_reason = None
            if os.path.realpath(path) in protect:
                protected_reason = "--protect"
            elif os.path.exists(os.path.join(path, PROTECT_MARKER)):
                protected_reason = ".keep"
            elif age_s < FRESH_SECONDS:
                protected_reason = "<24h"

            if protected_reason:
                status = "KEEP (protected)"
            elif referenced:
                status = ("DELETE (referenced, >keep-days)" if age_days > keep_days
                          else "KEEP (referenced, young)")
            else:
                status = ("DELETE (orphan, >orphan-days)" if age_days > orphan_days
                          else "KEEP (orphan, young)")

            entries.append({
                "path": path,
                "name": name,
                "group": sub,
                "status": status,
                "age_days": round(age_days, 1),
                "size_bytes": dir_size_bytes(path),
                "referenced": referenced,
                "referenced_by": referenced_by,
                "protected_reason": protected_reason,
                "delete": status.startswith("DELETE"),
            })
    return entries


def print_table(entries: list[dict]) -> None:
    header = ("status", "age_days", "size", "path", "referenced_by")
    rows = []
    for e in entries:
        refs = ", ".join(os.path.basename(p) for p in e["referenced_by"]) or "-"
        rows.append((
            e["status"],
            f"{e['age_days']:.1f}",
            human_size(e["size_bytes"]),
            e["path"],
            refs,
        ))
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    # do not pad the last column
    fmt = " | ".join(f"{{:<{w}}}" for w in widths[:-1]) + " | {}"
    print(fmt.format(*header))
    print("-+-".join("-" * w for w in widths[:-1]) + "-+-" + "-" * widths[-1])
    for row in rows:
        print(fmt.format(*row))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="GC for full-research / search-paper work directories in an Obsidian vault.")
    ap.add_argument("--root", required=True, help="vault root path")
    ap.add_argument("--keep-days", type=int, default=30,
                    help="retention for work dirs referenced by a vault note (default 30)")
    ap.add_argument("--orphan-days", type=int, default=7,
                    help="retention for unreferenced work dirs (default 7)")
    ap.add_argument("--dry-run", action="store_true", help="print only, never delete")
    ap.add_argument("--yes", action="store_true", help="confirm actual deletion")
    ap.add_argument("--protect", action="append", default=[],
                    help="path never to delete (repeatable)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="machine-readable output")
    args = ap.parse_args()

    root = os.path.abspath(os.path.expanduser(args.root))
    if not os.path.isdir(root):
        print(f"error: root not found: {root}", file=sys.stderr)
        return 2

    protect = {os.path.realpath(os.path.expanduser(p)) for p in args.protect}

    entries = collect(root, protect, args.keep_days, args.orphan_days)
    to_delete = [e for e in entries if e["delete"]]
    total_bytes = sum(e["size_bytes"] for e in to_delete)
    all_bytes = sum(e["size_bytes"] for e in entries)

    counts: dict[str, int] = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1

    def emit_summary(deleted=None, failed=None):
        if args.as_json:
            payload = {
                "root": root,
                "keep_days": args.keep_days,
                "orphan_days": args.orphan_days,
                "dry_run": args.dry_run,
                "counts": counts,
                "total_dirs": len(entries),
                "total_size_mib": round(all_bytes / (1024 * 1024), 1),
                "delete_count": len(to_delete),
                "delete_size_mib": round(total_bytes / (1024 * 1024), 1),
                "entries": entries,
            }
            if deleted is not None:
                payload["deleted"] = deleted
                payload["failed"] = failed
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print()
            for status in sorted(counts):
                print(f"{status}: {counts[status]}")
            print(f"total: {len(entries)} dirs, {all_bytes / (1024 * 1024):.1f} MiB")
            print(f"to delete: {len(to_delete)} dirs, {total_bytes / (1024 * 1024):.1f} MiB")
            if deleted is not None:
                print(f"deleted: {len(deleted)}, failed: {len(failed)}")

    if args.dry_run:
        if not args.as_json:
            print_table(entries)
        emit_summary()
        if not args.as_json:
            print("\nrerun with --yes to delete")
        return 0

    if not args.yes:
        if not args.as_json:
            print_table(entries)
        emit_summary()
        print("refusing to delete without --yes", file=sys.stderr)
        return 3

    deleted: list[str] = []
    failed: list[str] = []
    for e in to_delete:
        try:
            shutil.rmtree(e["path"])
            deleted.append(e["path"])
        except OSError as exc:
            print(f"error: failed to delete {e['path']}: {exc}", file=sys.stderr)
            failed.append(e["path"])

    emit_summary(deleted=deleted, failed=failed)

    if to_delete and not deleted:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
