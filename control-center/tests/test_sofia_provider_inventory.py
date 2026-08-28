from pathlib import Path

from gateway.provider_inventory import build_gateway_provider_inventory
from sofia_gateway_client import GatewayClientError
from sofia_provider_inventory import gateway_provider_inventory_probe
from sofia_runtime_inventory import load_runtime_inventory


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "runtime" / "sofia-os-canonical.json"


def test_live_gateway_inventory_is_preferred_when_contract_matches():
    baseline = load_runtime_inventory(INVENTORY)
    live = build_gateway_provider_inventory(baseline, {})
    calls = []

    def call_tool(url, tool, arguments):
        calls.append((url, tool, arguments))
        return live

    result = gateway_provider_inventory_probe(
        "http://127.0.0.1:8770/mcp",
        baseline,
        call_tool=call_tool,
    )

    assert result["live"] is True
    assert result["source"] == "gateway_live"
    assert result["error"] is None
    assert result["inventory"]["authority"] == "sofia-os-gateway"
    assert calls == [("http://127.0.0.1:8770/mcp", "gateway_provider_inventory", {})]


def test_gateway_inventory_failure_falls_back_with_same_operational_shape():
    baseline = load_runtime_inventory(INVENTORY)

    def call_tool(_url, _tool, _arguments):
        raise GatewayClientError("tool not installed")

    result = gateway_provider_inventory_probe(
        "http://127.0.0.1:8770/mcp",
        baseline,
        call_tool=call_tool,
    )

    inventory = result["inventory"]
    assert result["live"] is False
    assert result["source"] == "reconciled_baseline"
    assert result["error"] == "GatewayClientError"
    assert inventory["authority"] == "reconciled-baseline"
    assert inventory["mode"] == "read_only"
    assert inventory["summary"]["domains"] == 13
    assert inventory["summary"]["unknown"] == inventory["summary"]["providers"]
    assert all(
        component["readiness"] == "unknown"
        for domain in inventory["domains"]
        for component in domain["components"]
    )


def test_live_inventory_identity_mismatch_fails_closed():
    baseline = load_runtime_inventory(INVENTORY)
    live = build_gateway_provider_inventory(baseline, {})
    live["inventory_id"] = "wrong"

    result = gateway_provider_inventory_probe(
        "http://127.0.0.1:8770/mcp",
        baseline,
        call_tool=lambda *_args: live,
    )

    assert result["live"] is False
    assert result["source"] == "reconciled_baseline"


def test_live_inventory_runtime_target_change_fails_closed():
    baseline = load_runtime_inventory(INVENTORY)
    live = build_gateway_provider_inventory(baseline, {})
    live["domains"][0]["components"][0]["runtime_target"] = "unexpected-service"

    result = gateway_provider_inventory_probe(
        "http://127.0.0.1:8770/mcp",
        baseline,
        call_tool=lambda *_args: live,
    )

    assert result["live"] is False
    assert result["source"] == "reconciled_baseline"


def test_live_inventory_cannot_enable_lifecycle_during_reconciliation():
    baseline = load_runtime_inventory(INVENTORY)
    live = build_gateway_provider_inventory(baseline, {})
    live["domains"][0]["components"][0]["lifecycle"] = {
        "enabled": True,
        "actions": ["restart"],
    }

    result = gateway_provider_inventory_probe(
        "http://127.0.0.1:8770/mcp",
        baseline,
        call_tool=lambda *_args: live,
    )

    assert result["live"] is False
    assert result["source"] == "reconciled_baseline"
