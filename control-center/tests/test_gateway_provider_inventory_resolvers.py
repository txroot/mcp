import json
from pathlib import Path

import pytest

from gateway.provider_inventory_resolvers import (
    build_gateway_tool_resolvers,
    canonical_status_tools,
    intentionally_unresolved_components,
    validate_resolver_contract,
)
from sofia_runtime_inventory import inventory_from_dict, load_runtime_inventory


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "runtime" / "sofia-os-canonical.json"


def test_resolver_map_covers_every_canonical_component_without_guessing():
    inventory = load_runtime_inventory(INVENTORY_PATH)
    validate_resolver_contract(inventory)

    component_count = sum(len(domain.components) for domain in inventory.domains)
    assert component_count == 26
    assert len(canonical_status_tools()) == 24
    assert intentionally_unresolved_components() == (
        "prestashop/product-description-write",
        "trello/readwrite",
    )


def test_resolvers_call_only_the_static_read_only_status_contract():
    inventory = load_runtime_inventory(INVENTORY_PATH)
    calls = []

    def call_status_tool(tool_name, arguments):
        calls.append((tool_name, arguments))
        return {"status": "READY"}

    resolvers = build_gateway_tool_resolvers(inventory, call_status_tool)
    assert set(resolvers) == set(canonical_status_tools())
    assert resolvers["mail/read"]() == {"status": "READY"}
    assert calls == [("mail.read.status", {})]
    assert "trello/readwrite" not in resolvers


def test_resolver_contract_rejects_inventory_status_tool_drift():
    raw = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    for domain in raw["domains"]:
        if domain["domain_id"] == "mail":
            domain["components"][0]["status_tool"] = "mail.send.status"
            break
    inventory = inventory_from_dict(raw)

    with pytest.raises(ValueError, match="status contract mismatch"):
        validate_resolver_contract(inventory)


def test_resolver_contract_rejects_gateway_exposure_drift():
    raw = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    for domain in raw["domains"]:
        if domain["domain_id"] == "drive":
            domain["components"][0]["gateway_exposed"] = False
            break
    inventory = inventory_from_dict(raw)

    with pytest.raises(ValueError, match="non-exposed"):
        validate_resolver_contract(inventory)
