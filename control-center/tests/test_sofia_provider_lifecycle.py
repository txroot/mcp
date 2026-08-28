import pytest

from sofia_provider import manifest_from_dict


def base_manifest():
    return {
        "provider_id": "provider:memory/001",
        "name": "Memory",
        "version": "0.2.0",
        "description": "test",
        "gateway_required": True,
        "direct_external_exposure": False,
        "health": {
            "process_health": True,
            "provider_health": True,
            "source_health": False,
            "gateway_health": True,
        },
        "capabilities": [{
            "name": "memory.lifecycle.restart",
            "enforcement": "CONTROLLED",
            "risks": ["service_availability"],
            "requires_approval": True,
        }],
        "runtime": {
            "registry_id": "memory",
            "services": ["mcp-memory.service"],
            "lifecycle": {
                "start": "provider.memory.start",
                "stop": "provider.memory.stop",
                "restart": "provider.memory.restart",
            },
        },
    }


def test_valid_lifecycle_contract_is_accepted():
    manifest = manifest_from_dict(base_manifest())
    assert manifest.runtime is not None
    assert manifest.runtime.lifecycle_actions == {
        "start": "provider.memory.start",
        "stop": "provider.memory.stop",
        "restart": "provider.memory.restart",
    }


def test_lifecycle_action_must_match_runtime_identity():
    raw = base_manifest()
    raw["runtime"]["lifecycle"]["restart"] = "provider.prestashop.restart"
    with pytest.raises(ValueError, match="must be exactly"):
        manifest_from_dict(raw)


def test_lifecycle_actions_must_be_declared_as_complete_set():
    raw = base_manifest()
    raw["runtime"]["lifecycle"].pop("stop")
    with pytest.raises(ValueError, match="start, stop and restart together"):
        manifest_from_dict(raw)


def test_lifecycle_object_rejects_unknown_action():
    raw = base_manifest()
    raw["runtime"]["lifecycle"]["delete"] = "provider.memory.delete"
    with pytest.raises(ValueError, match="supports only"):
        manifest_from_dict(raw)
