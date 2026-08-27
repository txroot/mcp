from __future__ import annotations

import errno
import fcntl
import os
import pty
import secrets
import shlex
import signal
import struct
import subprocess
import termios
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HOME = Path.home().resolve()
MAX_BUFFER_BYTES = int(os.getenv("TERMINAL_MCP_BUFFER_BYTES", str(2 * 1024 * 1024)))
MAX_SESSIONS = int(os.getenv("TERMINAL_MCP_MAX_SESSIONS", "16"))


def _safe_cwd(value: str | None) -> Path:
    path = Path(value or HOME).expanduser().resolve()
    try:
        path.relative_to(HOME)
    except ValueError as exc:
        raise ValueError(f"cwd must be inside {HOME}") from exc
    if not path.is_dir():
        raise ValueError(f"cwd does not exist or is not a directory: {path}")
    return path


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    rows = max(2, min(int(rows), 300))
    cols = max(10, min(int(cols), 500))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@dataclass
class TerminalSession:
    session_id: str
    name: str
    cwd: str
    command: str
    master_fd: int
    process: subprocess.Popen[bytes]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cursor_start: int = 0
    cursor_end: int = 0
    chunks: deque[bytes] = field(default_factory=deque)
    buffered_bytes: int = 0
    closed: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self.lock:
            self.chunks.append(data)
            self.buffered_bytes += len(data)
            self.cursor_end += len(data)
            self.updated_at = time.time()
            while self.buffered_bytes > MAX_BUFFER_BYTES and self.chunks:
                old = self.chunks.popleft()
                self.buffered_bytes -= len(old)
                self.cursor_start += len(old)

    def read(self, after: int | None, max_bytes: int) -> dict[str, Any]:
        max_bytes = max(1, min(int(max_bytes), 262144))
        with self.lock:
            start = self.cursor_start if after is None else max(int(after), self.cursor_start)
            end = min(self.cursor_end, start + max_bytes)
            blob = b"".join(self.chunks)
            offset = max(0, start - self.cursor_start)
            data = blob[offset: offset + max(0, end - start)]
            return {
                "output": data.decode("utf-8", "replace"),
                "cursor": end,
                "buffer_start": self.cursor_start,
                "buffer_end": self.cursor_end,
                "truncated_before": after is not None and int(after) < self.cursor_start,
                "has_more": end < self.cursor_end,
            }

    def info(self) -> dict[str, Any]:
        rc = self.process.poll()
        return {
            "session_id": self.session_id,
            "name": self.name,
            "cwd": self.cwd,
            "command": self.command,
            "pid": self.process.pid,
            "state": "running" if rc is None and not self.closed else "exited",
            "return_code": rc,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cursor_start": self.cursor_start,
            "cursor_end": self.cursor_end,
            "buffered_bytes": self.buffered_bytes,
        }


class TerminalManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.RLock()

    def create(self, *, name: str = "Terminal", cwd: str | None = None, command: str | None = None,
               rows: int = 30, cols: int = 120) -> dict[str, Any]:
        with self._lock:
            live = sum(1 for s in self._sessions.values() if s.process.poll() is None)
            if live >= MAX_SESSIONS:
                raise RuntimeError(f"maximum live sessions reached ({MAX_SESSIONS})")
        workdir = _safe_cwd(cwd)
        shell = os.environ.get("SHELL") or "/bin/bash"
        cmd = (command or shell).strip()
        if not cmd:
            cmd = shell
        master_fd, slave_fd = pty.openpty()
        _set_winsize(slave_fd, rows, cols)
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env["TERM_PROGRAM"] = "Microlumin-MCP-Control-Center"
        try:
            proc = subprocess.Popen(
                [shell, "-lc", cmd] if command else [shell, "-l"],
                cwd=str(workdir), stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                env=env, start_new_session=True, close_fds=True,
            )
        finally:
            os.close(slave_fd)
        session_id = "term_" + secrets.token_hex(6)
        session = TerminalSession(session_id, (name or "Terminal")[:80], str(workdir), cmd, master_fd, proc)
        with self._lock:
            self._sessions[session_id] = session
        threading.Thread(target=self._reader, args=(session,), name=f"pty-reader-{session_id}", daemon=True).start()
        return session.info()

    def _reader(self, session: TerminalSession) -> None:
        try:
            while True:
                try:
                    data = os.read(session.master_fd, 65536)
                    if not data:
                        break
                    session.append(data)
                except OSError as exc:
                    if exc.errno in (errno.EIO, errno.EBADF):
                        break
                    raise
        finally:
            with session.lock:
                session.closed = True
                session.updated_at = time.time()
            try:
                os.close(session.master_fd)
            except OSError:
                pass

    def get(self, session_id: str) -> TerminalSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"unknown terminal session: {session_id}")
        return session

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [s.info() for s in sorted(self._sessions.values(), key=lambda x: x.created_at, reverse=True)]

    def read(self, session_id: str, after: int | None = None, max_bytes: int = 65536) -> dict[str, Any]:
        session = self.get(session_id)
        return {**session.info(), **session.read(after, max_bytes)}

    def write(self, session_id: str, data: str) -> dict[str, Any]:
        session = self.get(session_id)
        if session.process.poll() is not None or session.closed:
            raise RuntimeError("terminal session is not running")
        payload = data.encode("utf-8")
        written = os.write(session.master_fd, payload)
        session.updated_at = time.time()
        return {"session_id": session_id, "written_bytes": written, "cursor": session.cursor_end}

    def resize(self, session_id: str, rows: int, cols: int) -> dict[str, Any]:
        session = self.get(session_id)
        _set_winsize(session.master_fd, rows, cols)
        try:
            os.killpg(os.getpgid(session.process.pid), signal.SIGWINCH)
        except ProcessLookupError:
            pass
        return {"session_id": session_id, "rows": int(rows), "cols": int(cols)}

    def send_signal(self, session_id: str, signal_name: str) -> dict[str, Any]:
        session = self.get(session_id)
        key = signal_name.strip().upper().replace("SIG", "")
        allowed = {"INT": signal.SIGINT, "TERM": signal.SIGTERM, "HUP": signal.SIGHUP, "KILL": signal.SIGKILL, "QUIT": signal.SIGQUIT}
        if key not in allowed:
            raise ValueError(f"unsupported signal: {signal_name}")
        try:
            os.killpg(os.getpgid(session.process.pid), allowed[key])
        except ProcessLookupError:
            pass
        return {"session_id": session_id, "signal": key}

    def close(self, session_id: str, force: bool = False) -> dict[str, Any]:
        session = self.get(session_id)
        if session.process.poll() is None:
            sig = signal.SIGKILL if force else signal.SIGTERM
            try:
                os.killpg(os.getpgid(session.process.pid), sig)
            except ProcessLookupError:
                pass
            try:
                session.process.wait(timeout=1 if force else 2)
            except subprocess.TimeoutExpired:
                if not force:
                    try:
                        os.killpg(os.getpgid(session.process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        session.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
        return session.info()

    def delete(self, session_id: str, force: bool = False) -> dict[str, Any]:
        session = self.get(session_id)
        was_running = session.process.poll() is None
        self.close(session_id, force=force)
        with self._lock:
            removed = self._sessions.pop(session_id, None)
        return {
            "session_id": session_id,
            "deleted": removed is not None,
            "was_running": was_running,
            "return_code": session.process.poll(),
        }


manager = TerminalManager()
