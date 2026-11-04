#!/usr/bin/env bash
# sync-shared.sh — refresh the vendored copy of scripts/ and shared/ from the jadlis-search plugin.
# Usage: bash tools/sync-shared.sh jadlis-search--v2.0.0
set -euo pipefail
TAG="${1:?usage: sync-shared.sh <jadlis-search--vX.Y.Z>}"
REPO="https://gitlab.com/beCyborg/jadlis-search.git"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 --branch "$TAG" "$REPO" "$TMP"
SHA="$(git -C "$TMP" rev-parse HEAD)"
# Copy search's scripts over ours WITHOUT deleting anything: scripts/ also holds research-only files
# (science-research: chase.py, cocite.py, source-fetch.py — the core and the protocols call them). A wholesale replace deleted them.
mkdir -p "$ROOT/scripts"
cp -R "$TMP/scripts/." "$ROOT/scripts/"
extra=$(cd "$ROOT/scripts" && for f in *; do [ -e "$TMP/scripts/$f" ] || echo "$f"; done)
[ -n "$extra" ] && echo "kept research-only scripts: $(echo $extra | tr '\n' ' ')"
mkdir -p "$ROOT/shared"
cp "$TMP/shared/obsidian-write-contract.md" "$ROOT/shared/obsidian-write-contract.md"
printf 'jadlis-search %s %s\n' "$TAG" "$SHA" > "$ROOT/SHARED_FROM.txt"
echo "synced scripts/ + shared/ from $TAG ($SHA)"
