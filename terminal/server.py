from __future__ import annotations

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Annotated, Any
from urllib.parse import parse_qs, urlparse

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from terminal_manager import DEFAULT_TECHNICAL_WAIT_SECONDS, manager

HOST = "127.0.0.1"
SERVER_VERSION = "1.4.0"
ADMIN_PORT = int(os.getenv("TERMINAL_MCP_ADMIN_PORT", "18107"))
ADMIN_TOKEN = os.getenv("TERMINAL_MCP_ADMIN_TOKEN", "")
if not ADMIN_TOKEN:
    raise RuntimeError("TERMINAL_MCP_ADMIN_TOKEN is required")
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

mcp = MCPServer(
    "microlumin-interactive-terminal",
    title="Microlumin Interactive Terminal",
    version=SERVER_VERSION,
    instructions=(
        "Persistent interactive PTY sessions on the local Microlumin workstation. "
        "Sessions are shared with the local MCP Control Center terminal UI. "
        "Use terminal_read cursors to avoid repeating output. For compatibility with published schemas that do not expose "
        "terminal_wait, terminal_read without after_cursor is immediate, while terminal_read with after_cursor performs a short "
        "renewable blocking wait; repeat it while timed_out=true and intervention_timed_out=false. When available, terminal_wait "
        "is the explicit equivalent. Keep the ChatGPT turn open until the user's explicit stop marker or "
        "intervention_timed_out=true. The per-session intervention timeout defaults to one hour and can be overridden "
        "for a wait operation with intervention_timeout_seconds; the technical MCP wait remains short and renewable. "
        "Interactive sudo is supported when the host user is authorized. Never ask for, read, store, or send a sudo "
        "password through ChatGPT or terminal_write; instruct the user to type it directly in the Control Center PTY. "
        "Each session has a short human-readable terminal_code. Prefer that code in user-facing references and it may be "
        "used anywhere a session_id is accepted. Interaction timestamps are recorded as side-band actor events without "
        "storing typed content, so sudo/password input remains secret. Close terminal sessions proactively when persistence "
        "no longer has a concrete purpose. Prefer command-bound sessions that exit naturally for one-shot diagnostics; if an "
        "interactive shell was opened, call terminal_close when the task is complete. Keep a running session only for an active "
        "process/log stream, meaningful continuity, or expected user/physical intervention. Closing preserves buffered output; "
        "deletion is a separate cleanup decision. Use bounded parallelism proactively when work can be split into independent "
        "tasks: create multiple terminal sessions or concurrent processes for independent reads, builds, tests, or analyses and "
        "reconcile their results. Do not parallelize operations with ordering dependencies, concurrent writes to the same files, "
        "database migrations, destructive actions, or access to the same physical/shared resource unless that concurrency is "
        "explicitly known to be safe. Keep user-visible terminal actions auditable."
    ),
)


@mcp.tool(title="Create interactive terminal", annotations=WRITE)
def terminal_create(
    name: str = "Terminal",
    cwd: str | None = None,
    command: str | None = None,
    rows: Annotated[int, Field(ge=2, le=300)] = 30,
    cols: Annotated[int, Field(ge=10, le=500)] = 120,
    intervention_timeout_seconds: Annotated[int | None, Field(ge=0, le=604800)] = None,
) -> dict[str, Any]:
    """Create a persistent Linux PTY session. Omit command for an interactive login shell. Use separate sessions for independent parallel work when safe. The intervention timeout is the logical maximum time ChatGPT should renew waits for user/physical input; 0 means no logical limit and None inherits the MCP default."""
    return manager.create(name=name, cwd=cwd, command=command, rows=rows, cols=cols, intervention_timeout_seconds=intervention_timeout_seconds)


@mcp.tool(title="List interactive terminals", annotations=READ)
def terminal_list() -> list[dict[str, Any]]:
    """List terminal sessions, including running/exited state, PID, cwd and output cursors."""
    return manager.list()


@mcp.tool(title="Read terminal output", annotations=READ)
def terminal_read(
    session_id: str,
    after_cursor: Annotated[int | None, Field(ge=0)] = None,
    max_bytes: Annotated[int, Field(ge=1, le=262144)] = 65536,
) -> dict[str, Any]:
    """Read PTY output. Without after_cursor this is an immediate snapshot. With after_cursor it is a backward-compatible short blocking wait; repeat while timed_out=true and intervention_timed_out=false."""
    if after_cursor is None:
        result = manager.read(session_id, after=None, max_bytes=max_bytes)
        return {**result, "timed_out": False, "compatibility_mode": "snapshot"}
    result = manager.wait(
        session_id, after=after_cursor, max_bytes=max_bytes,
        timeout_seconds=DEFAULT_TECHNICAL_WAIT_SECONDS,
    )
    return {**result, "compatibility_mode": "incremental_read_wait"}


@mcp.tool(title="Wait for terminal output", annotations=READ)
def terminal_wait(
    session_id: str,
    after_cursor: Annotated[int, Field(ge=0)],
    timeout_seconds: Annotated[float, Field(ge=1, le=25)] = 20,
    max_bytes: Annotated[int, Field(ge=1, le=262144)] = 65536,
    intervention_timeout_seconds: Annotated[int | None, Field(ge=0, le=604800)] = None,
    reset_intervention_timer: bool = False,
) -> dict[str, Any]:
    """Block for one short technical wait. Reuse the returned cursor while timed_out=true. The MCP tracks a separate logical intervention deadline across calls; intervention_timed_out=true means stop renewing. Pass intervention_timeout_seconds to override/restart the logical timer for this wait cycle (0 = no logical limit), or reset_intervention_timer=true to restart using the session policy."""
    return manager.wait(
        session_id, after=after_cursor, max_bytes=max_bytes, timeout_seconds=timeout_seconds,
        intervention_timeout_seconds=intervention_timeout_seconds, reset_intervention_timer=reset_intervention_timer,
    )


@mcp.tool(title="Write to interactive terminal", annotations=WRITE)
def terminal_write(session_id: str, text: str) -> dict[str, Any]:
    """Send literal UTF-8 text/keystrokes to a running PTY. Include newline explicitly when needed. session_id may also be the short terminal_code."""
    return manager.write(session_id, text, actor="chatgpt")


@mcp.tool(title="Resize interactive terminal", annotations=WRITE)
def terminal_resize(
    session_id: str,
    rows: Annotated[int, Field(ge=2, le=300)],
    cols: Annotated[int, Field(ge=10, le=500)],
) -> dict[str, Any]:
    """Resize a PTY and notify the foreground process with SIGWINCH."""
    return manager.resize(session_id, rows, cols)


@mcp.tool(title="Signal interactive terminal", annotations=WRITE)
def terminal_signal(session_id: str, signal_name: str = "INT") -> dict[str, Any]:
    """Send INT, TERM, HUP, QUIT or KILL to the terminal process group."""
    return manager.send_signal(session_id, signal_name)


@mcp.tool(title="Close interactive terminal", annotations=DESTRUCTIVE)
def terminal_close(session_id: str, force: bool = False) -> dict[str, Any]:
    """Terminate a terminal session but keep it in the session list with its buffered output."""
    return manager.close(session_id, force=force)


@mcp.tool(title="Delete interactive terminal", annotations=DESTRUCTIVE)
def terminal_delete(session_id: str, force: bool = False) -> dict[str, Any]:
    """Terminate a terminal session if needed, then remove the session and its buffered output."""
    return manager.delete(session_id, force=force)


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "TerminalMCPAdmin/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Terminal-Admin-Token", ""), ADMIN_TOKEN)

    def _body(self) -> dict[str, Any]:
        n = min(int(self.headers.get("Content-Length", "0") or 0), 1048576)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self) -> None:
        p = urlparse(self.path)
        try:
            if p.path in ("/healthz", "/readyz"):
                self._json({"status": "ok", "version": SERVER_VERSION, "sessions": len(manager.list()), "wait_settings": manager.settings()}); return
            if p.path.startswith("/api/") and not self._authorized():
                self._json({"error": "unauthorized"}, 403); return
            if p.path == "/api/sessions":
                self._json({"sessions": manager.list()}); return
            if p.path == "/api/settings":
                self._json(manager.settings()); return
            if p.path == "/api/read":
                q = parse_qs(p.query)
                sid = q.get("session_id", [""])[0]
                after_raw = q.get("after", [None])[0]
                after = int(after_raw) if after_raw not in (None, "") else None
                self._json(manager.read(sid, after=after, max_bytes=131072)); return
            self._json({"error": "not found"}, 404)
        except KeyError as exc:
            self._json({"error": str(exc)}, 404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)

    def do_POST(self) -> None:
        try:
            if self.path.startswith("/api/") and not self._authorized():
                self._json({"error": "unauthorized"}, 403); return
            data = self._body()
            if self.path == "/api/create":
                timeout_value = data.get("intervention_timeout_seconds")
                self._json(manager.create(
                    name=str(data.get("name") or "Terminal"), cwd=data.get("cwd"), command=data.get("command"),
                    rows=int(data.get("rows", 30)), cols=int(data.get("cols", 120)),
                    intervention_timeout_seconds=None if timeout_value is None else int(timeout_value),
                )); return
            if self.path == "/api/settings":
                if "default_intervention_timeout_seconds" in data:
                    manager.set_default_intervention_timeout(
                        int(data["default_intervention_timeout_seconds"]),
                        apply_to_default_sessions=bool(data.get("apply_to_default_sessions", True)),
                    )
                if "closed_session_cleanup_seconds" in data:
                    manager.set_closed_session_cleanup_seconds(int(data["closed_session_cleanup_seconds"]))
                self._json(manager.settings()); return
            if self.path == "/api/configure-wait":
                timeout_value = data.get("intervention_timeout_seconds")
                self._json(manager.set_intervention_timeout(
                    str(data.get("session_id", "")), None if timeout_value is None else int(timeout_value),
                )); return
            if self.path == "/api/write":
                self._json(manager.write(str(data.get("session_id", "")), str(data.get("text", "")), actor="user")); return
            if self.path == "/api/resize":
                self._json(manager.resize(str(data.get("session_id", "")), int(data.get("rows", 30)), int(data.get("cols", 120)))); return
            if self.path == "/api/signal":
                self._json(manager.send_signal(str(data.get("session_id", "")), str(data.get("signal", "INT")))); return
            if self.path == "/api/close":
                self._json(manager.close(str(data.get("session_id", "")), bool(data.get("force", False)))); return
            if self.path == "/api/delete":
                self._json(manager.delete(str(data.get("session_id", "")), bool(data.get("force", False)))); return
            self._json({"error": "not found"}, 404)
        except KeyError as exc:
            self._json({"error": str(exc)}, 404)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)


def start_admin() -> None:
    ThreadingHTTPServer((HOST, ADMIN_PORT), AdminHandler).serve_forever()


def cleanup_loop() -> None:
    while True:
        try:
            manager.cleanup_expired_closed()
        except Exception:
            pass
        time.sleep(60)


def run() -> None:
    threading.Thread(target=start_admin, name="terminal-admin", daemon=True).start()
    threading.Thread(target=cleanup_loop, name="terminal-cleanup", daemon=True).start()
    port = int(os.getenv("TERMINAL_MCP_PORT", "8770"))
    mcp.run("streamable-http", host=HOST, port=port, stateless_http=True)


if __name__ == "__main__":
    run()
