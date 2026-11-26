#!/usr/bin/env bash
# CI only: point the given overlays at the image tag just built, then commit to main (GitOps -> Argo CD rolls it out).
# Usage: scripts/ci-bump-tag.sh <tag> <kustomization.yaml>...
set -euo pipefail
tag="$1"; shift
for f in "$@"; do sed -i -E "s/^(    newTag: ).*/\1${tag}/" "$f"; done
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add "$@"
git diff --cached --quiet && { echo "nothing to bump"; exit 0; }
git commit -m "lab: roll out image ${tag:0:7} [skip ci]"
for i in 1 2 3 4 5; do git pull --rebase origin main && git push origin HEAD:main && exit 0; sleep $((i*3)); done
exit 1
