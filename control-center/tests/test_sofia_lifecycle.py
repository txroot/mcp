import pytest

from sofia_lifecycle import LifecycleController, apply_lifecycle_availability


APPROVAL = "pvap_" + "a" * 32


def registry():
    return {
        "example": {
            "provider_manifest": {"gateway_required": True},
            "lifecycle_actions": {
                "start": "provider.example.start",
                "stop": "provider.example.stop",
                "restart": "provider.example.restart",
            },
        },
        "legacy": {"services": ["legacy.service"]},
    }


class FakeGateway:
    def __init__(self, allowed=None):
        self.allowed = list(allowed or [])
        self.calls = []

    def __call__(self, url, tool, arguments):
        self.calls.append((url, tool, dict(arguments)))
        if tool == "gateway_vm_status":
            return {"allowed_actions": list(self.allowed)}
        if tool == "gateway_prepare_operation":
            return {
                "approval_id": APPROVAL,
                "action": arguments["action"],
                "description": "prepared",
                "expires_at": "2026-08-28T00:30:00+00:00",
                "effect_applied": False,
                "confirmation_required": "CONFIRMO",
            }
        if tool == "gateway_execute_operation":
            return {
                "outcome": "PASS",
                "approval_id": arguments["approval_id"],
                "action": "provider.example.restart",
                "effect_applied": True,
                "output": [],
            }
        raise AssertionError(tool)


def test_prepare_is_blocked_when_gateway_does_not_advertise_action():
    fake = FakeGateway([])
    controller = LifecycleController(registry(), "http://127.0.0.1:8770/mcp", call_tool=fake)

    result = controller.prepare("example", "restart")

    assert result["ok"] is False
    assert result["code"] == "gateway_action_unavailable"
    assert [call[1] for call in fake.calls] == ["gateway_vm_status"]


def test_prepare_and_execute_are_two_phase_and_bound_to_local_approval():
    fake = FakeGateway(["provider.example.restart"])
    controller = LifecycleController(registry(), "http://127.0.0.1:8770/mcp", call_tool=fake)

    prepared = controller.prepare("example", "restart")
    assert prepared["ok"] is True
    assert prepared["effect_applied"] is False
    assert prepared["confirmation_required"] == "CONFIRMO"

    with pytest.raises(PermissionError, match="CONFIRMO"):
        controller.execute(APPROVAL, "yes")

    executed = controller.execute(APPROVAL, "CONFIRMO")
    assert executed["ok"] is True
    assert executed["effect_applied"] is True
    assert executed["gateway_action"] == "provider.example.restart"

    with pytest.raises(PermissionError, match="not prepared"):
        controller.execute(APPROVAL, "CONFIRMO")


def test_execute_rejects_approval_not_prepared_by_control_center():
    fake = FakeGateway(["provider.example.restart"])
    controller = LifecycleController(registry(), "http://127.0.0.1:8770/mcp", call_tool=fake)
    other = "pvap_" + "b" * 32

    with pytest.raises(PermissionError, match="not prepared"):
        controller.execute(other, "CONFIRMO")
    assert fake.calls == []


def test_local_expiry_fails_closed_before_gateway_execute():
    fake = FakeGateway(["provider.example.restart"])
    clock = [10.0]
    controller = LifecycleController(
        registry(),
        "http://127.0.0.1:8770/mcp",
        call_tool=fake,
        now=lambda: clock[0],
        local_ttl_seconds=5,
    )
    controller.prepare("example", "restart")
    clock[0] = 16.0

    with pytest.raises(PermissionError, match="expired"):
        controller.execute(APPROVAL, "CONFIRMO")
    assert [call[1] for call in fake.calls] == ["gateway_vm_status", "gateway_prepare_operation"]


def test_manifest_identity_prevents_cross_provider_action():
    data = registry()
    data["example"]["lifecycle_actions"]["restart"] = "provider.other.restart"
    fake = FakeGateway(["provider.other.restart"])
    controller = LifecycleController(data, "http://127.0.0.1:8770/mcp", call_tool=fake)

    with pytest.raises(PermissionError, match="identity"):
        controller.prepare("example", "restart")
    assert fake.calls == []


def test_status_availability_is_fail_closed_for_legacy_and_unadvertised_actions():
    payload = {"items": [{"id": "example"}, {"id": "legacy"}]}
    gateway = {
        "evidence": {"provider_lifecycle_actions": ["provider.example.restart"]}
    }

    result = apply_lifecycle_availability(payload, registry(), gateway)

    example = result["items"][0]["lifecycle"]
    assert example == {
        "mode": "gateway",
        "legacy_direct": False,
        "start": False,
        "stop": False,
        "restart": True,
    }
    legacy = result["items"][1]["lifecycle"]
    assert legacy["mode"] == "unavailable"
    assert legacy["legacy_direct"] is False
    assert not any(legacy[action] for action in ("start", "stop", "restart"))
