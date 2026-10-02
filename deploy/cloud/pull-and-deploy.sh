#!/usr/bin/env bash
# The GitHub Actions deploy key's forced command (deploy/cloud/README.md, "Automatic deploys"): bring
# ~/archive to origin/main, then run deploy.sh from the new checkout.
#
# The VM deploys main and nothing else. If its checkout has commits or edited tracked files that main does
# not have, a fast-forward is impossible and every deploy would fail; they are saved first (a branch for
# commits, a patch file for edits) and the checkout is reset to origin/main. VM-only settings belong in
# .env, which is untracked and never touched here.
set -euo pipefail

cd ~/archive
git fetch -q origin main

git merge --ff-only -q origin/main 2>/dev/null || true
# Up to date only if HEAD is exactly origin/main (not ahead of it) and no tracked file is edited.
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] || ! git diff --quiet HEAD; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backups=~/archive-backups
  mkdir -p "$backups"
  if ! git diff --quiet HEAD; then
    git diff HEAD >"$backups/vm-edits-$stamp.patch"
    echo "Saved edits to tracked files: $backups/vm-edits-$stamp.patch"
  fi
  if [ -n "$(git rev-list origin/main..HEAD)" ]; then
    git branch -f "vm-diverged-$stamp" HEAD
    echo "Saved VM-only commits on branch vm-diverged-$stamp:"
    git log --oneline origin/main..HEAD
  fi
  git checkout -q --force -B main origin/main
  echo "Reset ~/archive to origin/main ($(git rev-parse --short HEAD))."
fi

exec bash deploy/cloud/deploy.sh
