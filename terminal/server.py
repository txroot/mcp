from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Annotated, Any
from urllib.parse import parse_qs, urlparse

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from terminal_manager import manager

HOST = "127.0.0.1"
ADMIN_PORT = int(os.getenv("TERMINAL_MCP_ADMIN_PORT", "18107"))
ADMIN_TOKEN = os.getenv("TERMINAL_MCP_ADMIN_TOKEN", "")
if not ADMIN_TOKEN:
    raise RuntimeError("TERMINAL_MCP_ADMIN_TOKEN is required")
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

mcp = MCPServer(
    "microlumin-interactive-terminal",
    instructions=(
        "Persistent interactive PTY sessions on the local Microlumin workstation. "
        "Sessions are shared with the local MCP Control Center terminal UI. "
        "Use terminal_read cursors to avoid repeating output. For sustained interactive sessions, use terminal_wait "
        "repeatedly with the returned cursor and keep the ChatGPT turn open until the user's explicit stop marker. "
        "Keep user-visible terminal actions auditable."
    ),
)


@mcp.tool(title="Create interactive terminal", annotations=WRITE)
def terminal_create(
    name: str = "Terminal",
    cwd: str | None = None,
    command: str | None = None,
    rows: Annotated[int, Field(ge=2, le=300)] = 30,
    cols: Annotated[int, Field(ge=10, le=500)] = 120,
) -> dict[str, Any]:
    """Create a persistent Linux PTY session. Omit command for an interactive login shell."""
    return manager.create(name=name, cwd=cwd, command=command, rows=rows, cols=cols)


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
    """Read incremental PTY output. Pass the previous cursor as after_cursor on subsequent reads."""
    return manager.read(session_id, after=after_cursor, max_bytes=max_bytes)


@mcp.tool(title="Wait for terminal output", annotations=READ)
def terminal_wait(
    session_id: str,
    after_cursor: Annotated[int, Field(ge=0)],
    timeout_seconds: Annotated[float, Field(ge=1, le=25)] = 20,
    max_bytes: Annotated[int, Field(ge=1, le=262144)] = 65536,
) -> dict[str, Any]:
    """Block until new PTY output arrives, the session exits, or timeout expires. Reuse the returned cursor in a loop."""
    return manager.wait(session_id, after=after_cursor, max_bytes=max_bytes, timeout_seconds=timeout_seconds)


@mcp.tool(title="Write to interactive terminal", annotations=WRITE)
def terminal_write(session_id: str, text: str) -> dict[str, Any]:
    """Send literal UTF-8 text/keystrokes to a running PTY. Include newline explicitly when needed."""
    return manager.write(session_id, text)


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
                self._json({"status": "ok", "sessions": len(manager.list())}); return
            if p.path.startswith("/api/") and not self._authorized():
                self._json({"error": "unauthorized"}, 403); return
            if p.path == "/api/sessions":
                self._json({"sessions": manager.list()}); return
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
                self._json(manager.create(name=str(data.get("name") or "Terminal"), cwd=data.get("cwd"), command=data.get("command"), rows=int(data.get("rows", 30)), cols=int(data.get("cols", 120)))); return
            if self.path == "/api/write":
                self._json(manager.write(str(data.get("session_id", "")), str(data.get("text", "")))); return
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


def run() -> None:
    threading.Thread(target=start_admin, name="terminal-admin", daemon=True).start()
    port = int(os.getenv("TERMINAL_MCP_PORT", "8770"))
    mcp.run("streamable-http", host=HOST, port=port, stateless_http=True)


if __name__ == "__main__":
    run()
