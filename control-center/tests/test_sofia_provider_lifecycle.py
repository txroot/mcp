import pytest

from sofia_provider import manifest_from_dict


def base_manifest():
    return {
        "provider_id": "provider:example/001",
        "name": "Example",
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
            "name": "example.lifecycle.restart",
            "enforcement": "CONTROLLED",
            "risks": ["service_availability"],
            "requires_approval": True,
        }],
        "runtime": {
            "registry_id": "example",
            "services": ["example.service"],
            "lifecycle": {
                "start": "provider.example.start",
                "stop": "provider.example.stop",
                "restart": "provider.example.restart",
            },
        },
    }


def test_valid_lifecycle_contract_is_accepted():
    manifest = manifest_from_dict(base_manifest())
    assert manifest.runtime is not None
    assert manifest.runtime.lifecycle_actions == {
        "start": "provider.example.start",
        "stop": "provider.example.stop",
        "restart": "provider.example.restart",
    }


def test_lifecycle_action_must_match_runtime_identity():
    raw = base_manifest()
    raw["runtime"]["lifecycle"]["restart"] = "provider.other.restart"
    with pytest.raises(ValueError, match="must be exactly"):
        manifest_from_dict(raw)


def test_lifecycle_actions_must_be_declared_as_complete_set():
    raw = base_manifest()
    raw["runtime"]["lifecycle"].pop("stop")
    with pytest.raises(ValueError, match="start, stop and restart together"):
        manifest_from_dict(raw)


def test_lifecycle_object_rejects_unknown_action():
    raw = base_manifest()
    raw["runtime"]["lifecycle"]["delete"] = "provider.example.delete"
    with pytest.raises(ValueError, match="supports only"):
        manifest_from_dict(raw)


def test_disabled_runtime_cannot_keep_lifecycle_mapping():
    raw = base_manifest()
    raw["runtime"]["enabled"] = False
    raw["runtime"]["services"] = []

    with pytest.raises(ValueError, match="disabled runtime.lifecycle"):
        manifest_from_dict(raw)
