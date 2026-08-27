#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${HOME}/.local/share/mcp-control-center"
CONFIG_DIR="${HOME}/.config/mcp-control-center"
UNIT_DIR="${HOME}/.config/systemd/user"

mkdir -p "$APP_DIR" "$APP_DIR/static" "$APP_DIR/static/licenses" "$CONFIG_DIR" "$UNIT_DIR"
install -m 0644 "$SRC_DIR/server.py" "$APP_DIR/server.py"
install -m 0644 "$SRC_DIR/terminal.html" "$APP_DIR/terminal.html"
install -m 0644 "$SRC_DIR/static/xterm.js" "$APP_DIR/static/xterm.js"
install -m 0644 "$SRC_DIR/static/addon-fit.js" "$APP_DIR/static/addon-fit.js"
install -m 0644 "$SRC_DIR/static/xterm.css" "$APP_DIR/static/xterm.css"
install -m 0644 "$SRC_DIR/static/licenses/xterm-LICENSE" "$APP_DIR/static/licenses/xterm-LICENSE"
install -m 0644 "$SRC_DIR/static/licenses/addon-fit-LICENSE" "$APP_DIR/static/licenses/addon-fit-LICENSE"
install -m 0644 "$SRC_DIR/systemd/mcp-control-center.service" "$UNIT_DIR/mcp-control-center.service"

if [[ ! -f "$CONFIG_DIR/token" ]]; then
  python3 - <<'PY' > "$CONFIG_DIR/token"
import secrets
print(secrets.token_urlsafe(32))
PY
  chmod 600 "$CONFIG_DIR/token"
fi

python3 -m py_compile "$APP_DIR/server.py"
systemctl --user daemon-reload
systemctl --user enable mcp-control-center.service
systemctl --user restart mcp-control-center.service

echo "MCP Control Center: http://127.0.0.1:18100"
