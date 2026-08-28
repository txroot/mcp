#!/usr/bin/env bash
set -euo pipefail

PROD_CONTAINER="${SOFIA_GATEWAY_PROD_CONTAINER:-pedrovault-mcp-production}"
REPO_ROOT="${SOFIA_MCP_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
STATUS_GATEWAY_URL="${PV_PROVIDER_STATUS_MCP_URL:-http://127.0.0.1:8770/mcp}"

if [[ ! -d "$REPO_ROOT/control-center/gateway" ]]; then
  echo "ERROR: repository root not found: $REPO_ROOT" >&2
  exit 2
fi

running="$(docker inspect -f '{{.State.Running}}' "$PROD_CONTAINER" 2>/dev/null || true)"
health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$PROD_CONTAINER" 2>/dev/null || true)"
base_image="$(docker inspect -f '{{.Config.Image}}' "$PROD_CONTAINER" 2>/dev/null || true)"

if [[ "$running" != "true" ]]; then
  echo "ERROR: production Gateway container is not running" >&2
  exit 3
fi
if [[ "$health" != "healthy" ]]; then
  echo "ERROR: production Gateway health must be healthy before canary build (got: $health)" >&2
  exit 4
fi
if [[ -z "$base_image" ]]; then
  echo "ERROR: cannot resolve production Gateway base image" >&2
  exit 5
fi
if ! docker image inspect "$base_image" >/dev/null 2>&1; then
  echo "ERROR: production Gateway image is not available locally" >&2
  exit 6
fi

short_sha="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || printf 'nogit')"
CANARY_IMAGE="${SOFIA_PROVIDER_INVENTORY_CANARY_IMAGE:-pedrovault-mcp:provider-inventory-canary-${short_sha}}"
workdir="$(mktemp -d -t sofia-provider-inventory-canary.XXXXXX)"
trap 'rm -rf "$workdir"' EXIT

mkdir -p "$workdir/app/runtime/adapters/mcp_self_hosted" "$workdir/app/runtime-bundle"
docker cp \
  "$PROD_CONTAINER:/app/runtime/adapters/mcp_self_hosted/server.py" \
  "$workdir/app/runtime/adapters/mcp_self_hosted/server.py"

python3 "$REPO_ROOT/control-center/gateway/canary/apply_overlay.py" \
  --repo-root "$REPO_ROOT" \
  --runtime-root "$workdir/app"

cat > "$workdir/Dockerfile" <<'DOCKERFILE'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY app/runtime/adapters/mcp_self_hosted/server.py /app/runtime/adapters/mcp_self_hosted/server.py
COPY app/runtime/adapters/mcp_self_hosted/provider_inventory.py /app/runtime/adapters/mcp_self_hosted/provider_inventory.py
COPY app/runtime/adapters/mcp_self_hosted/provider_inventory_resolvers.py /app/runtime/adapters/mcp_self_hosted/provider_inventory_resolvers.py
COPY app/runtime/adapters/mcp_self_hosted/provider_status_client.py /app/runtime/adapters/mcp_self_hosted/provider_status_client.py
COPY app/runtime/adapters/mcp_self_hosted/provider_inventory_smoke.py /app/runtime/adapters/mcp_self_hosted/provider_inventory_smoke.py
COPY app/sofia_runtime_inventory.py /app/sofia_runtime_inventory.py
COPY app/runtime-bundle/sofia-os-provider-inventory.json /app/runtime-bundle/sofia-os-provider-inventory.json
DOCKERFILE

docker build \
  --build-arg "BASE_IMAGE=$base_image" \
  --tag "$CANARY_IMAGE" \
  "$workdir"

docker run --rm \
  --workdir /app \
  --entrypoint python3 \
  "$CANARY_IMAGE" \
  -c 'import runtime.adapters.mcp_self_hosted.server; print("CANARY_SERVER_IMPORT_OK")'

docker run --rm \
  --network host \
  --workdir /app \
  --entrypoint python3 \
  --env "PV_PROVIDER_STATUS_MCP_URL=$STATUS_GATEWAY_URL" \
  "$CANARY_IMAGE" \
  -m runtime.adapters.mcp_self_hosted.provider_inventory_smoke

echo "SOFIA_PROVIDER_INVENTORY_CANARY_PASS image=$CANARY_IMAGE base=$base_image"
