#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${HOME}/.config/terminal-mcp"
ENV_FILE="${CONFIG_DIR}/runtime.env"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${TERMINAL_MCP_PORT:-8770}"
ADMIN_PORT="${TERMINAL_MCP_ADMIN_PORT:-18107}"
mkdir -p "$UNIT_DIR" "$CONFIG_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  python3 - <<'PYTOKEN' > "$ENV_FILE"
import secrets
print("TERMINAL_MCP_ADMIN_TOKEN=" + secrets.token_urlsafe(32))
PYTOKEN
  chmod 600 "$ENV_FILE"
fi
"$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
cat > "$UNIT_DIR/mcp-terminal.service" <<UNIT
[Unit]
Description=Microlumin Interactive Terminal MCP
After=default.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
Environment=TERMINAL_MCP_PORT=$PORT
Environment=TERMINAL_MCP_ADMIN_PORT=$ADMIN_PORT
Environment=TERMINAL_MCP_MAX_SESSIONS=16
Environment=TERMINAL_MCP_BUFFER_BYTES=2097152
EnvironmentFile=$ENV_FILE
ExecStart=$PROJECT_DIR/.venv/bin/python server.py
Restart=always
RestartSec=3
NoNewPrivileges=false
PrivateTmp=true

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable mcp-terminal.service
systemctl --user restart mcp-terminal.service
ready=0
for _ in {1..50}; do
  if curl -fsS "http://127.0.0.1:$ADMIN_PORT/healthz" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.1
done
if [[ "$ready" != "1" ]]; then
  echo "Terminal MCP did not become healthy on port $ADMIN_PORT" >&2
  exit 5
fi
if systemctl --user cat mcp-terminal-tunnel.service >/dev/null 2>&1; then
  systemctl --user restart mcp-terminal-tunnel.service
fi
echo "Terminal MCP: http://127.0.0.1:$PORT/mcp"
echo "Terminal local admin API: http://127.0.0.1:$ADMIN_PORT"
