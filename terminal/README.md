# Interactive Terminal MCP

Persistent Linux PTY sessions shared between ChatGPT and the local MCP Control Center, including a blocking-wait mode for sustained terminal conversations inside an active ChatGPT turn.

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
- `terminal_wait` — block for new output, enabling sustained interactive ChatGPT turns
- `terminal_read` — incremental output using a byte cursor
- `terminal_write` — send literal terminal input
- `terminal_resize` — resize rows/columns
- `terminal_signal` — send INT/TERM/HUP/QUIT/KILL
- `terminal_close` — terminate a session but keep it listed with buffered output
- `terminal_delete` — terminate if needed, then remove the session and buffered output

## Session model

Each session has a random `term_<hex>` ID and a bounded in-memory output ring buffer. The default buffer is 2 MiB and the maximum number of live sessions is 16. Cursors let clients fetch only output not previously seen. Both the browser and ChatGPT write to the same PTY; there is deliberately no hidden second shell.

Sessions survive browser detach/reload but not a restart of `mcp-terminal.service` or the host. Systemd terminates the service cgroup, including child PTY processes, on restart/stop.


## Sustained ChatGPT interaction (`terminal_wait`)

A persistent PTY and a persistent ChatGPT turn are different things. The PTY survives browser detach, but ChatGPT only continues calling tools while its current response is still running.

For a sustained terminal conversation, the caller should:

1. read the initial output and keep the returned cursor;
2. call `terminal_wait(session_id, after_cursor=cursor, timeout_seconds=20)`;
3. on timeout, call `terminal_wait` again without ending the ChatGPT response;
4. when user output arrives, process only the new bytes, reply through `terminal_write`, advance past the reply/terminal echo, then wait again;
5. end the ChatGPT response only after an explicit user stop marker such as `FECHAR TESTE`.

`terminal_wait` blocks efficiently on a per-session condition and wakes when new PTY bytes arrive or when the session closes. Its **technical** timeout is intentionally bounded to 25 seconds so calls can be safely renewed through the MCP/OpenAI tunnel. A separate **logical intervention timeout** is tracked across those calls. The default is 3600 seconds (1 hour), configurable in the Control Center. `intervention_timeout_seconds` can override/restart it for one ChatGPT wait cycle; `0` means no MCP logical limit. When the logical deadline expires, `intervention_timed_out=true` is returned and the PTY remains running.

Example logical loop:

```text
cursor = terminal_read(...).cursor
while true:
    event = terminal_wait(after_cursor=cursor, timeout_seconds=20)
    if event.timed_out:
        continue
    cursor = event.cursor
    if user_requested_stop(event.output):
        break
    terminal_write(reply)
    cursor = advance_past_terminal_echo()
```

This does **not** create a background ChatGPT daemon. Once ChatGPT finalizes the turn, it stops calling `terminal_wait`; the PTY remains alive, but a new ChatGPT turn is required to resume interaction.

When using a shell as the conversation surface, explicit markers such as `[ANDRE -> CHATGPT]` and `[CHATGPT -> ANDRE]` are recommended to distinguish user input from prompts, command echo and ChatGPT's own output.

## Intervention wait policy

The wait policy is stored by the Terminal MCP, not only in the browser:

- global default: `~/.config/terminal-mcp/settings.json`;
- default: 3600 seconds;
- supported range: 0 to 604800 seconds (7 days);
- `0`: unlimited logical wait;
- new sessions inherit the global default unless they receive an explicit override;
- an existing session can inherit the default or use its own override from the Control Center;
- changing the global default updates sessions that are still configured to inherit it;
- an already-running wait cycle keeps its own deadline until it is satisfied, restarted, or expires;
- expiry never closes or deletes the PTY.

The Control Center presets are 5 min, 15 min, 30 min, 1 h, 4 h and Unlimited. When a logical wait is active the UI shows its deadline (`Waiting until HH:MM`).

## Security

- all listeners bind to `127.0.0.1`;
- browser write/read operations are proxied by the token-protected Control Center;
- the loopback PTY/admin `/api/*` additionally requires a random `X-Terminal-Admin-Token` generated at install time;
- cwd is restricted to paths inside the Unix user's home directory;
- terminal commands execute initially with the permissions of the user running the service;
- `NoNewPrivileges` is deliberately disabled for this developer terminal so standard setuid tools such as `sudo` can perform their normal authentication flow; this does **not** grant root automatically;
- if `sudo` asks for a password, the password must be typed by the user directly into the Control Center PTY. ChatGPT must never ask for it in chat, send it with `terminal_write`, store it, or copy it into logs;
- while a password is being entered, the terminal disables echo, so the typed password is not appended to the PTY output buffer;
- the OpenAI tunnel is a separate optional service and must expose only port 8770;
- secrets must not be placed in Git or profile YAML files.

This MCP is intentionally powerful: shell input can modify local files and services accessible to the Unix user. Treat MCP write/close/signal tools as consequential operations and keep visible/auditable terminal sessions for interactive work.


## Control Center semantics

The browser UI is not the session owner. It attaches to sessions managed by `mcp-terminal.service`.

- **Close** terminates the process but deliberately keeps the session metadata and buffered output visible.
- **Delete** terminates the process if necessary and removes the session plus its buffer from the manager.
- Reloading or leaving `/terminal` only detaches the browser; it does not close a running session.

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

The tunnel unit waits for the Terminal MCP health endpoint before starting. `install_local.sh` also waits for the MCP to become healthy and restarts an installed terminal tunnel afterwards. This ordering prevents tunnel discovery from getting stuck on an initial connection-refused race.

On ChatGPT Business, a published MCP app uses a frozen snapshot of its tools and input schemas. Changing the live MCP server or its advertised MCP version does **not** update that snapshot. Tool/schema changes must be tested in Developer mode and then recreated/republished as a new app revision. Keep the previous published app available until the replacement is validated.

The MCP server advertises an explicit version so clients can detect schema revisions. After the MCP tool schema changes, an already-open ChatGPT conversation may still expose the previous cached tool set. Verify local MCP discovery and tunnel readiness first; if they are correct, start a new ChatGPT conversation or reconnect/reload the **Interactive Terminal** app so the tool schema is discovered again.
