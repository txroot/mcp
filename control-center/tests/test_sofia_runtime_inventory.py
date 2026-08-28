import json
from pathlib import Path

import pytest

from sofia_runtime_inventory import inventory_from_dict, load_runtime_inventory


CONTROL_CENTER_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = CONTROL_CENTER_ROOT / "runtime" / "sofia-os-canonical.json"


def test_repository_runtime_inventory_matches_reconciled_architecture():
    inventory = load_runtime_inventory(INVENTORY_PATH)

    assert inventory.host == "eletrix-server"
    assert inventory.authority == "runtime-reconciled"
    assert inventory.lifecycle_policy == "disabled_until_gateway_provider_inventory"

    domains = {domain.domain_id: domain for domain in inventory.domains}
    assert set(domains) == {
        "sofia-core",
        "ssh",
        "pc-edge",
        "prestashop",
        "mail",
        "calendar",
        "tasks",
        "sheets",
        "contacts",
        "drive",
        "location",
        "elektro3",
        "trello",
    }
    assert "memory" not in domains
    assert "google-analytics" not in domains
    assert "host-tools" not in domains

    prestashop_targets = {component.target for component in domains["prestashop"].components}
    assert "pedrovault-prestashop-provider-production-r55" in prestashop_targets
    assert "pedrovault-prestashop-category-writer-r82" in prestashop_targets
    assert "pedrovault-prestashop-sofiabridge-readonly-provider.service" in prestashop_targets

    trello = domains["trello"].components[0]
    assert trello.target == "pedrovault-trello-readwrite-provider.service"
    assert trello.gateway_exposed is False
    assert trello.lifecycle_enabled is False

    assert all(
        component.lifecycle_enabled is False
        for domain in inventory.domains
        for component in domain.components
    )


def test_inventory_round_trip_is_serializable():
    inventory = load_runtime_inventory(INVENTORY_PATH)
    payload = inventory.to_dict()

    assert payload["inventory_id"] == inventory.inventory_id
    assert len(payload["domains"]) == 13
    json.dumps(payload)


def test_inventory_rejects_lifecycle_enablement_during_reconciliation():
    raw = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    raw["domains"][0]["components"][0]["lifecycle_enabled"] = True

    with pytest.raises(ValueError, match="lifecycle must remain disabled"):
        inventory_from_dict(raw)


def test_inventory_rejects_obsolete_domain_reintroduction():
    raw = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    raw["domains"].append(
        {
            "domain_id": "memory",
            "name": "Memory",
            "components": [
                {
                    "component_id": "memory",
                    "role": "read",
                    "kind": "systemd",
                    "target": "mcp-memory.service",
                    "status_tool": None,
                    "gateway_exposed": False,
                    "lifecycle_enabled": False,
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="obsolete domains present"):
        inventory_from_dict(raw)
