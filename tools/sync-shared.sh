#!/usr/bin/env bash
# sync-shared.sh — refresh the vendored copy of scripts/ and shared/ from the search plugin.
# Usage: bash tools/sync-shared.sh search--v1.2.0
set -euo pipefail
TAG="${1:?usage: sync-shared.sh <search--vX.Y.Z>}"
REPO="https://github.com/beCyborg/jadlis-search.git"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 --branch "$TAG" "$REPO" "$TMP"
SHA="$(git -C "$TMP" rev-parse HEAD)"
rm -rf "$ROOT/scripts"
cp -R "$TMP/scripts" "$ROOT/scripts"
mkdir -p "$ROOT/shared"
cp "$TMP/shared/obsidian-write-contract.md" "$ROOT/shared/obsidian-write-contract.md"
printf 'search %s %s\n' "$TAG" "$SHA" > "$ROOT/SHARED_FROM.txt"
echo "synced scripts/ + shared/ from $TAG ($SHA)"
