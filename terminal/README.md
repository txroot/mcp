# Interactive Terminal MCP

Persistent Linux PTY sessions shared between ChatGPT and the local MCP Control Center.

## Purpose

The service solves workflows where a one-shot command is not enough: serial monitors, SSH shells, Flutter/IDF monitors, REPLs, `journalctl -f`, Docker logs and long-running development tools. Closing or navigating away from the browser does not close the PTY. The session lives while `mcp-terminal.service` remains running.

## Interfaces

- MCP: `http://127.0.0.1:8770/mcp`
- local PTY/admin API: `http://127.0.0.1:18107`
- user UI: integrated in MCP Control Center at `http://127.0.0.1:18100/terminal`

The PTY/admin API binds only to loopback. The Control Center proxies browser operations and requires its local control token. The OpenAI tunnel points only at the MCP endpoint on port 8770; it never exposes port 18107 or the Control Center UI.

## MCP tools

- `terminal_create` — create a persistent PTY; blank command starts a login shell
- `terminal_list` — list sessions and state
- `terminal_read` — incremental output using a byte cursor
- `terminal_write` — send literal terminal input
- `terminal_resize` — resize rows/columns
- `terminal_signal` — send INT/TERM/HUP/QUIT/KILL
- `terminal_close` — terminate a session but keep it listed with buffered output
- `terminal_delete` — terminate if needed, then remove the session and buffered output

## Session model

Each session has a random `term_<hex>` ID and a bounded in-memory output ring buffer. The default buffer is 2 MiB and the maximum number of live sessions is 16. Cursors let clients fetch only output not previously seen. Both the browser and ChatGPT write to the same PTY; there is deliberately no hidden second shell.

Sessions survive browser detach/reload but not a restart of `mcp-terminal.service` or the host. Systemd terminates the service cgroup, including child PTY processes, on restart/stop.

## Security

- all listeners bind to `127.0.0.1`;
- browser write/read operations are proxied by the token-protected Control Center;
- the loopback PTY/admin `/api/*` additionally requires a random `X-Terminal-Admin-Token` generated at install time;
- cwd is restricted to paths inside the Unix user's home directory;
- terminal commands execute with the permissions of the user running the service, never as root automatically;
- the OpenAI tunnel is a separate optional service and must expose only port 8770;
- secrets must not be placed in Git or profile YAML files.

This MCP is intentionally powerful: shell input can modify local files and services accessible to the Unix user. Treat MCP write/close/signal tools as consequential operations and keep visible/auditable terminal sessions for interactive work.

## Install

```bash
./scripts/install_local.sh
systemctl --user status mcp-terminal.service
```

Then install/restart the Control Center from `../control-center/scripts/install_local.sh`.

## Tests

```bash
.venv/bin/pytest -q
```

## OpenAI tunnel

The current development host uses the `terminal` tunnel profile and `mcp-terminal-tunnel.service`. On a new host, use `scripts/configure_tunnel.sh tunnel_<id>` after creating or assigning the tunnel in the OpenAI control plane.
