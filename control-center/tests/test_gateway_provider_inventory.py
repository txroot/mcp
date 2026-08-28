import json
from pathlib import Path

from gateway.provider_inventory import (
    build_gateway_provider_inventory,
    classify_readiness,
    register_gateway_provider_inventory,
)
from sofia_runtime_inventory import load_runtime_inventory


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "runtime" / "sofia-os-canonical.json"


def test_readiness_classifier_handles_common_provider_shapes():
    assert classify_readiness({"status": "READY"})[0] == "healthy"
    assert classify_readiness({"provider_status": "READY"})[0] == "healthy"
    assert classify_readiness({"auth_ready": True, "read_ready": True})[0] == "healthy"
    assert classify_readiness({"auth_ready": True, "write_ready": True})[0] == "healthy"
    assert classify_readiness({"auth_ready": False})[0] == "unhealthy"
    assert classify_readiness({"status": "DEGRADED"})[0] == "degraded"
    assert classify_readiness({})[0] == "unknown"


def test_inventory_minimizes_status_payload_and_keeps_unwired_unknown():
    inventory = load_runtime_inventory(INVENTORY)

    def failed_resolver():
        raise RuntimeError("do not leak this secret text")

    result = build_gateway_provider_inventory(
        inventory,
        {
            "sofia-core/gateway": lambda: {
                "status": "READY",
                "graph_fingerprint": "secret-ish-operational-detail",
            },
            "mail/read": lambda: {
                "auth_ready": True,
                "read_ready": True,
                "credential_ref": "opaque:must-not-be-returned",
            },
            "mail/send": failed_resolver,
        },
    )

    encoded = json.dumps(result)
    assert result["authority"] == "sofia-os-gateway"
    assert result["mode"] == "read_only"
    assert result["summary"]["domains"] == 13
    assert result["summary"]["healthy"] == 2
    assert result["summary"]["unhealthy"] == 1
    assert result["summary"]["unknown"] > 0
    assert "credential_ref" not in encoded
    assert "opaque:must-not-be-returned" not in encoded
    assert "graph_fingerprint" not in encoded
    assert "secret-ish-operational-detail" not in encoded
    assert "do not leak this secret text" not in encoded

    providers = {
        component["provider_id"]: component
        for domain in result["domains"]
        for component in domain["components"]
    }
    assert providers["mail/read"]["readiness"] == "healthy"
    assert providers["mail/send"]["readiness"] == "unhealthy"
    assert providers["trello/readwrite"]["readiness"] == "unknown"
    assert all(provider["lifecycle"] == {"enabled": False, "actions": []} for provider in providers.values())


def test_registration_uses_read_only_contract_and_minimal_audit():
    inventory = load_runtime_inventory(INVENTORY)
    captured = {}
    audits = []

    class FakeServer:
        def tool(self, *, title, annotations):
            captured["title"] = title
            captured["annotations"] = annotations

            def decorate(function):
                captured["function"] = function
                return function

            return decorate

    handler = register_gateway_provider_inventory(
        FakeServer(),
        annotations="READ_ONLY_LOCAL",
        inventory=inventory,
        status_resolvers={"sofia-core/gateway": lambda: {"status": "READY"}},
        audit=lambda event, outcome, metadata: audits.append((event, outcome, metadata)),
    )

    result = handler()
    assert captured["title"] == "Provider inventory/status"
    assert captured["annotations"] == "READ_ONLY_LOCAL"
    assert result["mode"] == "read_only"
    assert audits[0][0:2] == ("PROVIDER_INVENTORY_READ", "PASS")
    assert audits[0][2]["external_effect"] is False
