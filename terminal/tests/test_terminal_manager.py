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


def test_intervention_timeout_default_and_session_override(tmp_path):
    settings = tmp_path / "settings.json"
    m = TerminalManager(settings_path=settings)
    assert m.settings()["default_intervention_timeout_seconds"] == 3600

    inherited = m.create(name="default-wait", command="cat")
    explicit = m.create(name="explicit-wait", command="cat", intervention_timeout_seconds=900)
    try:
        assert inherited["intervention_timeout_seconds"] == 3600
        assert inherited["intervention_timeout_source"] == "default"
        assert explicit["intervention_timeout_seconds"] == 900
        assert explicit["intervention_timeout_source"] == "session"

        m.set_default_intervention_timeout(1800)
        assert m.get(inherited["session_id"]).info()["intervention_timeout_seconds"] == 1800
        assert m.get(explicit["session_id"]).info()["intervention_timeout_seconds"] == 900

        reverted = m.set_intervention_timeout(explicit["session_id"], None)
        assert reverted["intervention_timeout_seconds"] == 1800
        assert reverted["intervention_timeout_source"] == "default"
    finally:
        m.close(inherited["session_id"], force=True)
        m.close(explicit["session_id"], force=True)


def test_intervention_timeout_settings_persist(tmp_path):
    settings = tmp_path / "settings.json"
    m = TerminalManager(settings_path=settings)
    m.set_default_intervention_timeout(14400)
    assert settings.exists()
    assert oct(settings.stat().st_mode & 0o777) == "0o600"

    m2 = TerminalManager(settings_path=settings)
    assert m2.settings()["default_intervention_timeout_seconds"] == 14400


def test_wait_tracks_logical_deadline_and_keeps_session_open(tmp_path):
    m = TerminalManager(settings_path=tmp_path / "settings.json")
    info = m.create(name="logical-timeout", command="cat", intervention_timeout_seconds=60)
    sid = info["session_id"]
    try:
        first = m.read(sid, after=0)
        session = m.get(sid)
        session.start_wait_state(60)
        with session.lock:
            session.wait_deadline = time.time() - 0.01
        result = m.wait(sid, after=first["cursor"], timeout_seconds=0.1)
        assert result["intervention_timed_out"] is True
        assert result["wait_state"] == "timed_out"
        assert result["state"] == "running"
    finally:
        m.close(sid, force=True)


def test_wait_output_completes_logical_wait_cycle(tmp_path):
    import threading

    m = TerminalManager(settings_path=tmp_path / "settings.json")
    info = m.create(name="logical-output", command="cat", intervention_timeout_seconds=3600)
    sid = info["session_id"]
    first = m.read(sid, after=0)

    def delayed_write():
        time.sleep(0.08)
        m.write(sid, "physical-action-done\n")

    try:
        t = threading.Thread(target=delayed_write)
        t.start()
        result = m.wait(sid, after=first["cursor"], timeout_seconds=1)
        t.join(timeout=1)
        assert "physical-action-done" in result["output"]
        assert result["intervention_timed_out"] is False
        assert result["wait_state"] == "idle"
        assert result["wait_deadline"] is None
    finally:
        m.close(sid, force=True)


def test_process_exit_clears_wait_state(tmp_path):
    m = TerminalManager(settings_path=tmp_path / "settings.json")
    info = m.create(name="exit-wait", command="sleep 0.08")
    sid = info["session_id"]
    session = m.get(sid)
    session.start_wait_state(3600)
    end = time.time() + 2
    while time.time() < end and session.process.poll() is None:
        time.sleep(0.02)
    # Reader thread marks closed immediately after PTY EOF; allow it to finish its finally block.
    end = time.time() + 1
    while time.time() < end and not session.closed:
        time.sleep(0.01)
    state = session.info()
    assert state["state"] == "exited"
    assert state["wait_state"] == "idle"
    assert state["wait_deadline"] is None


def test_terminal_code_is_human_readable_and_resolves():
    m = TerminalManager()
    info = m.create(name="code", command="cat")
    try:
        code = info["terminal_code"]
        assert len(code) == 4
        assert code.isalnum()
        assert "0" not in code and "1" not in code and "I" not in code and "O" not in code
        assert m.get(code).session_id == info["session_id"]
        assert m.get(code.lower()).session_id == info["session_id"]
    finally:
        m.close(info["session_id"], force=True)


def test_interaction_events_timestamp_actor_without_storing_content():
    m = TerminalManager()
    info = m.create(name="events", command="cat")
    sid = info["session_id"]
    try:
        before = time.time()
        result = m.write(sid, "secret-looking-input", actor="user")
        event = result["interaction_event"]
        assert event["actor"] == "user"
        assert event["at"] >= before
        assert "text" not in event and "content" not in event and "data" not in event
        # More characters from the same intervention do not create another event until Enter.
        assert "interaction_event" not in m.write(sid, "-continued", actor="user")
        m.write(sid, "\n", actor="user")
        m.write(sid, "next\n", actor="user")
        read = m.read(sid, after=0)
        actors = [item["actor"] for item in read["interaction_events"]]
        assert actors.count("user") >= 2
        assert all("secret-looking-input" not in repr(item) for item in read["interaction_events"])
    finally:
        m.close(sid, force=True)

def test_delete_accepts_short_terminal_code():
    m = TerminalManager()
    info = m.create(name="delete-code", command="cat")
    result = m.delete(info["terminal_code"], force=True)
    assert result["deleted"] is True
    assert result["session_id"] == info["session_id"]
    assert result["terminal_code"] == info["terminal_code"]
    assert all(item["session_id"] != info["session_id"] for item in m.list())


def test_closed_session_cleanup_defaults_to_24h_and_persists(tmp_path):
    settings = tmp_path / "settings.json"
    m = TerminalManager(settings_path=settings)
    assert m.settings()["closed_session_cleanup_seconds"] == 24 * 3600
    m.set_closed_session_cleanup_seconds(7 * 24 * 3600)
    m2 = TerminalManager(settings_path=settings)
    assert m2.settings()["closed_session_cleanup_seconds"] == 7 * 24 * 3600


def test_cleanup_removes_only_closed_sessions_after_ttl(tmp_path):
    m = TerminalManager(settings_path=tmp_path / "settings.json")
    m.set_closed_session_cleanup_seconds(60)
    old = m.create(name="old-closed", command="true")
    running = m.create(name="running-old", command="cat")
    recent = m.create(name="recent-closed", command="true")
    try:
        for sid in (old["session_id"], recent["session_id"]):
            session = m.get(sid)
            end = time.time() + 2
            while time.time() < end and session.closed_at is None:
                time.sleep(0.01)
            assert session.closed_at is not None
        m.get(old["session_id"]).closed_at = time.time() - 61
        m.get(running["session_id"]).updated_at = time.time() - 999999
        removed = m.cleanup_expired_closed()
        assert [item["session_id"] for item in removed] == [old["session_id"]]
        remaining = {item["session_id"] for item in m.list()}
        assert running["session_id"] in remaining
        assert recent["session_id"] in remaining
        assert old["session_id"] not in remaining
    finally:
        if running["session_id"] in {item["session_id"] for item in m.list()}:
            m.delete(running["session_id"], force=True)


def test_cleanup_can_be_disabled(tmp_path):
    m = TerminalManager(settings_path=tmp_path / "settings.json")
    m.set_closed_session_cleanup_seconds(0)
    info = m.create(name="keep-closed", command="true")
    session = m.get(info["session_id"])
    end = time.time() + 2
    while time.time() < end and session.closed_at is None:
        time.sleep(0.01)
    assert session.closed_at is not None
    session.closed_at = time.time() - 999999
    assert m.cleanup_expired_closed() == []
    assert info["session_id"] in {item["session_id"] for item in m.list()}
