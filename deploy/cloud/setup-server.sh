#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu 24.04 cloud VM (see deploy/cloud/README.md):
# swap for a 4 GB machine, Docker Engine, and a checkout of the repository in ~/archive.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/UAnjana000/LESSGOOO.git}"
SWAP_SIZE="${SWAP_SIZE:-6G}"

# The api keeps two ONNX models loaded (~2.8 GB); swap absorbs worker spikes on a 4 GB VM.
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l "$SWAP_SIZE" /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

if [ -d ~/archive/.git ]; then
  git -C ~/archive pull --ff-only
else
  git clone "$REPO_URL" ~/archive
fi

free -h
echo "Done. Log out and back in once so the docker group applies, then follow deploy/cloud/README.md."
