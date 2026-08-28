#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${HOME}/.local/share/mcp-control-center"
CONFIG_DIR="${HOME}/.config/mcp-control-center"
UNIT_DIR="${HOME}/.config/systemd/user"
PROVIDERS_DIR="${APP_DIR}/providers"

mkdir -p "$APP_DIR" "$CONFIG_DIR" "$UNIT_DIR" "$PROVIDERS_DIR"
install -m 0644 "$SRC_DIR/server.py" "$APP_DIR/server.py"
install -m 0644 "$SRC_DIR/sofia_server.py" "$APP_DIR/sofia_server.py"
install -m 0644 "$SRC_DIR/sofia_provider.py" "$APP_DIR/sofia_provider.py"
install -m 0644 "$SRC_DIR/sofia_registry.py" "$APP_DIR/sofia_registry.py"
install -m 0644 "$SRC_DIR/sofia_source_health.py" "$APP_DIR/sofia_source_health.py"
install -m 0644 "$SRC_DIR/sofia_gateway_health.py" "$APP_DIR/sofia_gateway_health.py"
install -m 0644 "$SRC_DIR/sofia_health.py" "$APP_DIR/sofia_health.py"
install -m 0644 "$SRC_DIR/sofia_ui.py" "$APP_DIR/sofia_ui.py"
install -m 0644 "$SRC_DIR"/providers/*.provider.json "$PROVIDERS_DIR/"
install -m 0644 "$SRC_DIR/systemd/mcp-control-center.service" "$UNIT_DIR/mcp-control-center.service"

if [[ ! -f "$CONFIG_DIR/token" ]]; then
  python3 - <<'PY' > "$CONFIG_DIR/token"
import secrets
print(secrets.token_urlsafe(32))
PY
  chmod 600 "$CONFIG_DIR/token"
fi

python3 -m py_compile \
  "$APP_DIR/server.py" \
  "$APP_DIR/sofia_server.py" \
  "$APP_DIR/sofia_provider.py" \
  "$APP_DIR/sofia_registry.py" \
  "$APP_DIR/sofia_source_health.py" \
  "$APP_DIR/sofia_gateway_health.py" \
  "$APP_DIR/sofia_health.py" \
  "$APP_DIR/sofia_ui.py"
systemctl --user daemon-reload
systemctl --user enable mcp-control-center.service
systemctl --user restart mcp-control-center.service

echo "Sofia Control Center: http://127.0.0.1:18100"