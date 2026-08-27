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

def test_delete_exited_session_removes_it():
    m = TerminalManager()
    info = m.create(name="done", command="true")
    sid = info["session_id"]
    end = time.time() + 2
    while time.time() < end and m.get(sid).process.poll() is None:
        time.sleep(0.02)
    result = m.delete(sid)
    assert result["deleted"] is True
    assert result["was_running"] is False
    assert all(item["session_id"] != sid for item in m.list())
    try:
        m.get(sid)
    except KeyError:
        pass
    else:
        raise AssertionError("deleted session is still addressable")


def test_delete_running_session_terminates_and_removes_it():
    m = TerminalManager()
    info = m.create(name="running", command="cat")
    sid = info["session_id"]
    proc = m.get(sid).process
    result = m.delete(sid)
    assert result["deleted"] is True
    assert result["was_running"] is True
    assert proc.poll() is not None
    assert all(item["session_id"] != sid for item in m.list())


def test_wait_blocks_until_new_output():
    import threading

    m = TerminalManager()
    info = m.create(name="wait", command="cat")
    sid = info["session_id"]
    first = m.read(sid, after=0)

    def delayed_write():
        time.sleep(0.08)
        m.write(sid, "wake-up-99\n")

    t = threading.Thread(target=delayed_write)
    t.start()
    started = time.monotonic()
    result = m.wait(sid, after=first["cursor"], timeout_seconds=1)
    elapsed = time.monotonic() - started
    t.join(timeout=1)
    assert elapsed >= 0.05
    assert result["timed_out"] is False
    assert "wake-up-99" in result["output"]
    m.close(sid, force=True)
