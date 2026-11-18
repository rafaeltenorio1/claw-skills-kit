#!/usr/bin/env bash
# Build, configure and start the operator OpenClaw gateway in Docker. Safe to run again.
#   docker/up.sh            build + bootstrap + start + checks
# Env: CSK_ENV_FILE (secrets file), CSK_HOST_PORT (default 18790).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${CSK_HOST_PORT:-18790}"
say() { echo "up: $*"; }

say "building image"
docker compose build --quiet gateway

# OpenClaw refuses config writes from another container while a gateway owns the state.
say "stopping a running gateway, if any"
docker compose stop gateway > /dev/null 2>&1 || true

say "bootstrapping state (one-off container)"
docker compose run --rm --no-deps --entrypoint /opt/claw-skills-kit/bootstrap.sh gateway

say "starting gateway"
docker compose up -d gateway

say "waiting for the gateway to be ready"
ready=""
for _ in $(seq 1 90); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/readyz" 2>/dev/null; then ready=yes; break; fi
    sleep 2
done
if [ -z "$ready" ]; then
    say "gateway not ready after 3 minutes; see: docker compose -f docker/compose.yml logs gateway"
    exit 1
fi

say "checking skills"
docker compose exec -T gateway openclaw skills list > /dev/null
say "ready: Control UI at http://127.0.0.1:$PORT/ (token: the OPENCLAW_GATEWAY_TOKEN in your env file)"
