#!/usr/bin/env bash
# Runs on the VM after `git pull`: rebuild changed images, restart what changed, and wait until every
# service reports healthy. The GitHub Actions deploy key's forced command runs the pull and then this
# script (see deploy/cloud/README.md), so the key can do nothing else.
set -euo pipefail

cd ~/archive
COMPOSE=(docker compose -f docker-compose.yml -f deploy/cloud/docker-compose.cloud.yml)

echo "Deploying $(git rev-parse --short HEAD): $(git log -1 --format=%s)"
"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d

status=""
for _ in $(seq 1 60); do
  status=$("${COMPOSE[@]}" ps --format '{{.Service}}={{.Health}}')
  if ! grep -qv '=healthy$' <<<"$status"; then
    echo "$status"
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 5
done

echo "Not every service is healthy after 5 minutes:"
echo "$status"
"${COMPOSE[@]}" logs --tail 40 api worker proxy
exit 1
