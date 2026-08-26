#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="${HOME}/.config/prestashop-mcp"
ENV_FILE="${CONFIG_DIR}/runtime.env"
UNIT_DIR="${HOME}/.config/systemd/user"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PRESTASHOP_MCP_PORT:-8769}"

mkdir -p "$CONFIG_DIR" "$UNIT_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Created $ENV_FILE. Fill in the local secrets before starting the service."
fi

"$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

cat > "$UNIT_DIR/mcp-prestashop.service" <<UNIT
[Unit]
Description=PrestaShop MCP Server (Eletrix, read-only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PROJECT_DIR/.venv/bin/python -c "from server import mcp; mcp.run('streamable-http', host='127.0.0.1', port=$PORT, stateless_http=True)"
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable mcp-prestashop.service

echo "Installed mcp-prestashop.service on 127.0.0.1:$PORT"
echo "After configuring the bridge credentials: systemctl --user restart mcp-prestashop.service"
