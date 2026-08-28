from types import SimpleNamespace

from gateway.provider_lifecycle_actions import build_provider_lifecycle_actions
from gateway import provider_lifecycle_runner as runner


def test_broker_fragment_has_exactly_nine_static_actions():
    actions = build_provider_lifecycle_actions(runner="/runner", interlock="/lock")

    assert set(actions) == {
        f"provider.{provider}.{action}"
        for provider in ("prestashop", "google-analytics", "memory")
        for action in ("start", "stop", "restart")
    }
    assert len(actions) == 9
    for name, definition in actions.items():
        provider, action = name.split(".")[1:]
        command = definition["commands"][0]
        assert command == [
            "/lock",
            "run",
            "--owner",
            f"broker:{name}",
            "--",
            "/runner",
            provider,
            action,
        ]
        assert definition["timeout"] == 120


def test_runner_provider_and_unit_allowlist_is_static():
    assert runner.PROVIDERS == {
        "prestashop": ("mcp-prestashop.service", "mcp-prestashop-tunnel.service"),
        "google-analytics": ("mcp-google-analytics.service", "mcp-google-analytics-tunnel.service"),
        "memory": ("mcp-memory.service", "mcp-memory-tunnel.service"),
    }
    assert runner.ACTIONS == {"start", "stop", "restart"}


def test_runner_executes_declared_units_and_requires_postflight(monkeypatch):
    calls = []
    state_calls = {}

    def fake_state(unit):
        count = state_calls.get(unit, 0)
        state_calls[unit] = count + 1
        return "inactive" if count == 0 else "active"

    def fake_run(command, timeout=30):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "unit_state", fake_state)
    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(
        runner,
        "_systemctl_command",
        lambda *args: ["systemctl", "--user", *args],
    )

    result = runner.execute("memory", "start")

    assert result["postflight"] == "PASS"
    assert result["before"] == {
        "mcp-memory.service": "inactive",
        "mcp-memory-tunnel.service": "inactive",
    }
    assert result["after"] == {
        "mcp-memory.service": "active",
        "mcp-memory-tunnel.service": "active",
    }
    assert calls == [
        ["systemctl", "--user", "start", "mcp-memory.service"],
        ["systemctl", "--user", "start", "mcp-memory-tunnel.service"],
    ]


def test_stop_reverses_units(monkeypatch):
    calls = []
    state_calls = {}

    def fake_state(unit):
        count = state_calls.get(unit, 0)
        state_calls[unit] = count + 1
        return "active" if count == 0 else "inactive"

    def fake_run(command, timeout=30):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "unit_state", fake_state)
    monkeypatch.setattr(runner, "_run", fake_run)
    monkeypatch.setattr(runner, "_systemctl_command", lambda *args: list(args))

    runner.execute("prestashop", "stop")

    assert calls == [
        ["stop", "mcp-prestashop-tunnel.service"],
        ["stop", "mcp-prestashop.service"],
    ]
