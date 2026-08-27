#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 || "$1" != tunnel_* ]]; then
  echo "Usage: $0 tunnel_<id>" >&2
  exit 2
fi
TUNNEL_ID="$1"
PROFILE_DIR="${HOME}/.config/tunnel-client"
UNIT_DIR="${HOME}/.config/systemd/user"
RUNTIME_ENV="${PROFILE_DIR}/host-tools-runtime.env"
if ! command -v tunnel-client >/dev/null 2>&1; then echo "tunnel-client not found" >&2; exit 3; fi
if [[ ! -f "$RUNTIME_ENV" ]]; then echo "Missing $RUNTIME_ENV with CONTROL_PLANE_API_KEY" >&2; exit 4; fi
mkdir -p "$PROFILE_DIR" "$UNIT_DIR"
cat > "${PROFILE_DIR}/terminal.yaml" <<YAML
config_version: 1
control_plane:
  base_url: "https://api.openai.com"
  tunnel_id: "${TUNNEL_ID}"
  api_key: "env:CONTROL_PLANE_API_KEY"
health:
  listen_addr: "127.0.0.1:18108"
  url_file: "/tmp/terminal-tunnel-health.url"
admin_ui:
  open_browser: false
log:
  level: info
  format: json
mcp:
  server_urls:
    - channel: main
      url: "http://127.0.0.1:8770/mcp"
YAML
cat > "${UNIT_DIR}/mcp-terminal-tunnel.service" <<'UNIT'
[Unit]
Description=Interactive Terminal MCP Secure Tunnel
After=mcp-terminal.service network-online.target
Wants=network-online.target
Requires=mcp-terminal.service

[Service]
Type=simple
EnvironmentFile=%h/.config/tunnel-client/host-tools-runtime.env
ExecStartPre=/bin/bash -lc 'for i in {1..50}; do curl -fsS http://127.0.0.1:18107/healthz >/dev/null 2>&1 && exit 0; sleep 0.1; done; exit 1'
ExecStart=/usr/local/bin/tunnel-client run --profile terminal
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable mcp-terminal-tunnel.service
systemctl --user restart mcp-terminal-tunnel.service
echo "Terminal tunnel profile installed: ${TUNNEL_ID}"
echo "Tunnel Health/Admin: http://127.0.0.1:18108"
