import json
from pathlib import Path

import pytest

from sofia_provider import manifest_from_dict
from sofia_registry import load_control_center_registry
from sofia_source_health import apply_source_health


PROVIDERS_DIR = Path(__file__).resolve().parents[1] / "providers"


def test_google_analytics_repository_manifest_suppresses_obsolete_runtime(tmp_path: Path):
    result = load_control_center_registry(
        legacy_registry={"google-analytics": {"name": "legacy"}},
        providers_dir=PROVIDERS_DIR,
        home=tmp_path / "home",
    )

    manifest = result.manifests["provider:google-analytics/legacy-control-center/001"]

    assert "google-analytics" not in result.registry
    assert "google-analytics" in result.suppressed_ids
    assert "google-analytics" not in result.migrated_ids
    assert manifest.gateway_required is True
    assert manifest.direct_external_exposure is False
    assert manifest.runtime is not None
    assert manifest.runtime.enabled is False
    assert manifest.runtime.source_probe == ""
    assert manifest.capabilities == ()


def test_source_health_uses_existing_result_without_duplicate_probe():
    calls = []
    payload = {
        "items": [
            {
                "id": "google-analytics",
                "all_active": True,
                "state": "online",
                "source_access": {"ok": True, "text": "GA4 data access OK"},
            }
        ]
    }
    registry = {
        "google-analytics": {
            "source_probe": "google_analytics",
            "tunnel_configured": True,
        }
    }

    def probe():
        calls.append(True)
        return {"ok": True, "text": "unexpected duplicate call"}

    result = apply_source_health(payload, registry, {"google_analytics": probe})

    assert calls == []
    assert result["items"][0]["source_health"] == "healthy"
    assert result["items"][0]["state"] == "online"


def test_source_health_calls_allowlisted_probe_when_result_is_missing():
    payload = {
        "items": [
            {
                "id": "google-analytics",
                "all_active": True,
                "state": "online",
            }
        ]
    }
    registry = {
        "google-analytics": {
            "source_probe": "google_analytics",
            "tunnel_configured": True,
        }
    }

    result = apply_source_health(
        payload,
        registry,
        {"google_analytics": lambda: {"ok": True, "text": "GA4 data access OK"}},
    )

    item = result["items"][0]
    assert item["source_access"]["ok"] is True
    assert item["source_health"] == "healthy"
    assert item["state"] == "online"


def test_unknown_source_probe_fails_closed():
    payload = {
        "items": [
            {
                "id": "google-analytics",
                "all_active": True,
                "state": "online",
            }
        ]
    }
    registry = {
        "google-analytics": {
            "source_probe": "not_registered",
            "tunnel_configured": True,
        }
    }

    result = apply_source_health(payload, registry, {})

    item = result["items"][0]
    assert item["source_access"]["ok"] is False
    assert item["source_health"] == "unhealthy"
    assert item["state"] == "degraded"


def test_unhealthy_source_degrades_active_provider():
    payload = {
        "items": [
            {
                "id": "google-analytics",
                "all_active": True,
                "state": "online",
            }
        ]
    }
    registry = {
        "google-analytics": {
            "source_probe": "google_analytics",
            "tunnel_configured": True,
        }
    }

    result = apply_source_health(
        payload,
        registry,
        {"google_analytics": lambda: {"ok": False, "text": "GA4 access denied"}},
    )

    assert result["items"][0]["state"] == "degraded"
    assert result["items"][0]["source_health"] == "unhealthy"


def test_source_probe_cannot_contain_command_syntax():
    raw = json.loads((PROVIDERS_DIR / "google-analytics.provider.json").read_text())
    raw["runtime"]["source_probe"] = "python -c unsafe"

    with pytest.raises(ValueError, match="symbolic lowercase identifier"):
        manifest_from_dict(raw)
