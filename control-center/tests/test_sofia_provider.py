import json
from pathlib import Path

import pytest

from sofia_provider import (
    EnforcementLevel,
    HealthState,
    aggregate_health,
    load_manifest,
    manifest_from_dict,
)


def base_manifest() -> dict:
    return {
        "provider_id": "provider:example/001",
        "name": "Example Provider",
        "version": "0.1.0",
        "description": "Test provider",
        "gateway_required": True,
        "direct_external_exposure": False,
        "health": {
            "process_health": True,
            "provider_health": True,
            "source_health": True,
            "gateway_health": True,
        },
        "capabilities": [
            {
                "name": "example.read",
                "enforcement": "FULL",
                "risks": [],
                "requires_approval": False,
            },
            {
                "name": "example.write",
                "enforcement": "CONTROLLED",
                "risks": ["external_write"],
                "requires_approval": True,
            },
        ],
    }


def test_valid_manifest_is_gateway_first():
    manifest = manifest_from_dict(base_manifest())

    assert manifest.provider_id == "provider:example/001"
    assert manifest.gateway_required is True
    assert manifest.direct_external_exposure is False
    assert manifest.capability("example.read").enforcement == EnforcementLevel.FULL
    assert manifest.capability("example.write").requires_approval is True


def test_direct_external_exposure_is_rejected():
    raw = base_manifest()
    raw["direct_external_exposure"] = True

    with pytest.raises(ValueError, match="direct_external_exposure"):
        manifest_from_dict(raw)


def test_gateway_bypass_is_rejected():
    raw = base_manifest()
    raw["gateway_required"] = False

    with pytest.raises(ValueError, match="gateway_required"):
        manifest_from_dict(raw)


def test_duplicate_capability_is_rejected():
    raw = base_manifest()
    raw["capabilities"].append(dict(raw["capabilities"][0]))

    with pytest.raises(ValueError, match="duplicate capability"):
        manifest_from_dict(raw)


def test_scalar_risks_are_rejected():
    raw = base_manifest()
    raw["capabilities"][0]["risks"] = "customer_data"

    with pytest.raises(ValueError, match="capability.risks"):
        manifest_from_dict(raw)


def test_scalar_runtime_services_are_rejected():
    raw = base_manifest()
    raw["runtime"] = {
        "registry_id": "example",
        "services": "example.service",
    }

    with pytest.raises(ValueError, match="runtime.services"):
        manifest_from_dict(raw)


def test_load_manifest_from_json(tmp_path: Path):
    path = tmp_path / "provider.json"
    path.write_text(json.dumps(base_manifest()), encoding="utf-8")

    manifest = load_manifest(path)

    assert manifest.name == "Example Provider"
    assert len(manifest.capabilities) == 2


def test_health_aggregation():
    assert aggregate_health({}) == HealthState.UNKNOWN
    assert aggregate_health({"process": "healthy", "provider": "healthy"}) == HealthState.HEALTHY
    assert aggregate_health({"process": "healthy", "source": "unknown"}) == HealthState.DEGRADED
    assert aggregate_health({"process": "healthy", "source": "degraded"}) == HealthState.DEGRADED
    assert aggregate_health({"process": "healthy", "source": "unhealthy"}) == HealthState.UNHEALTHY
