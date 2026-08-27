import time
from pathlib import Path

from terminal_manager import TerminalManager


def wait_for_text(manager, sid, text, timeout=3):
    end = time.time() + timeout
    cursor = None
    out = ""
    while time.time() < end:
        result = manager.read(sid, after=cursor, max_bytes=65536)
        cursor = result["cursor"]
        out += result["output"]
        if text in out:
            return out
        time.sleep(0.03)
    raise AssertionError(f"missing {text!r} in {out!r}")


def test_command_output_and_cursor():
    m = TerminalManager()
    info = m.create(name="test", command="printf 'hello\\n'; sleep 0.1")
    out = wait_for_text(m, info["session_id"], "hello")
    assert "hello" in out
    first = m.read(info["session_id"], after=0)
    second = m.read(info["session_id"], after=first["cursor"])
    assert second["output"] == ""


def test_interactive_write():
    m = TerminalManager()
    info = m.create(name="cat", command="cat")
    sid = info["session_id"]
    m.write(sid, "shared-input-42\\n")
    assert "shared-input-42" in wait_for_text(m, sid, "shared-input-42")
    m.close(sid, force=True)


def test_cwd_outside_home_is_rejected(tmp_path):
    m = TerminalManager()
    outside = Path("/tmp").resolve()
    try:
        outside.relative_to(Path.home().resolve())
    except ValueError:
        pass
    else:
        return
    try:
        m.create(cwd=str(outside), command="true")
    except ValueError as exc:
        assert "cwd must be inside" in str(exc)
    else:
        raise AssertionError("outside-home cwd accepted")
