import json
from pathlib import Path

import pytest

from sofia_registry import load_control_center_registry


CONTROL_CENTER_ROOT = Path(__file__).resolve().parents[1]


def runtime_manifest(registry_id: str = "prestashop") -> dict:
    return {
        "provider_id": "provider:prestashop/001",
        "name": "PrestaShop",
        "version": "0.1.0",
        "description": "Read-only provider",
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
                "name": "prestashop.catalog.read",
                "enforcement": "FULL",
                "risks": [],
                "requires_approval": False,
            }
        ],
        "runtime": {
            "registry_id": registry_id,
            "services": ["mcp-prestashop.service"],
            "profile": "prestashop",
            "mcp": "http://127.0.0.1:8769/mcp",
            "health": "http://127.0.0.1:18105",
            "admin": "http://127.0.0.1:18105/ui",
            "kind": "HTTP + Tunnel",
            "tunnel_configured": True,
            "probe_type": "http",
            "tools_probe": {
                "type": "http",
                "python": "${HOME}/app/.venv/bin/python",
                "url": "http://127.0.0.1:8769/mcp",
            },
        },
    }


def suppression_manifest(registry_id: str = "memory") -> dict:
    return {
        "provider_id": f"provider:{registry_id}/legacy/001",
        "name": f"{registry_id} legacy",
        "version": "0.1.0",
        "description": "suppression only",
        "gateway_required": True,
        "direct_external_exposure": False,
        "health": {
            "process_health": False,
            "provider_health": False,
            "source_health": False,
            "gateway_health": False,
        },
        "capabilities": [],
        "runtime": {
            "registry_id": registry_id,
            "enabled": False,
            "services": [],
        },
    }


def write_manifest(directory: Path, name: str, payload: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manifest_overrides_only_migrated_legacy_entry(tmp_path: Path):
    providers = tmp_path / "providers"
    providers.mkdir()
    write_manifest(providers, "prestashop.provider.json", runtime_manifest())
    legacy = {
        "prestashop": {"name": "Legacy PrestaShop", "services": ["legacy.service"]},
        "memory": {"name": "Memory", "services": ["memory.service"]},
    }

    result = load_control_center_registry(legacy, providers, tmp_path / "home")

    assert result.migrated_ids == ("prestashop",)
    assert result.suppressed_ids == ()
    assert result.registry["prestashop"]["name"] == "PrestaShop"
    assert result.registry["prestashop"]["services"] == ["mcp-prestashop.service"]
    assert result.registry["memory"] == legacy["memory"]
    assert result.registry["prestashop"]["provider_manifest"]["gateway_required"] is True


def test_disabled_manifest_suppresses_legacy_entry(tmp_path: Path):
    providers = tmp_path / "providers"
    providers.mkdir()
    write_manifest(providers, "memory.provider.json", suppression_manifest("memory"))
    legacy = {
        "memory": {"name": "Legacy Memory", "services": ["memory.service"]},
        "other": {"name": "Other", "services": ["other.service"]},
    }

    result = load_control_center_registry(legacy, providers, tmp_path)

    assert result.migrated_ids == ()
    assert result.suppressed_ids == ("memory",)
    assert "memory" not in result.registry
    assert result.registry["other"] == legacy["other"]


def test_home_placeholder_is_expanded(tmp_path: Path):
    providers = tmp_path / "providers"
    providers.mkdir()
    write_manifest(providers, "prestashop.provider.json", runtime_manifest())
    home = tmp_path / "sofia"

    result = load_control_center_registry({}, providers, home)

    assert result.registry["prestashop"]["tools_probe"]["python"] == str(home / "app/.venv/bin/python")


def test_manifest_without_runtime_is_loaded_but_does_not_change_registry(tmp_path: Path):
    providers = tmp_path / "providers"
    providers.mkdir()
    payload = runtime_manifest()
    payload.pop("runtime")
    write_manifest(providers, "reference.provider.json", payload)
    legacy = {"memory": {"name": "Memory", "services": ["memory.service"]}}

    result = load_control_center_registry(legacy, providers, tmp_path)

    assert result.registry == legacy
    assert result.migrated_ids == ()
    assert result.suppressed_ids == ()
    assert "provider:prestashop/001" in result.manifests


def test_duplicate_runtime_registry_id_is_rejected_even_when_suppressed(tmp_path: Path):
    providers = tmp_path / "providers"
    providers.mkdir()
    first = suppression_manifest("memory")
    second = suppression_manifest("memory")
    second["provider_id"] = "provider:memory-copy/001"
    write_manifest(providers, "a.provider.json", first)
    write_manifest(providers, "b.provider.json", second)

    with pytest.raises(ValueError, match="duplicate runtime.registry_id"):
        load_control_center_registry({}, providers, tmp_path)


def test_invalid_manifest_fails_closed(tmp_path: Path):
    providers = tmp_path / "providers"
    providers.mkdir()
    payload = runtime_manifest()
    payload["direct_external_exposure"] = True
    write_manifest(providers, "prestashop.provider.json", payload)

    with pytest.raises(ValueError, match="direct_external_exposure"):
        load_control_center_registry({}, providers, tmp_path)


def test_repository_manifests_suppress_all_obsolete_legacy_cards(tmp_path: Path):
    legacy = {
        "host-tools": {"name": "Host Tools", "services": ["old"]},
        "google-tasks": {"name": "Google Tasks", "services": ["old"]},
        "memory": {"name": "Memory", "services": ["old"]},
        "google-analytics": {"name": "Google Analytics", "services": ["old"]},
        "prestashop": {"name": "PrestaShop", "services": ["old"]},
    }
    result = load_control_center_registry(
        legacy_registry=legacy,
        providers_dir=CONTROL_CENTER_ROOT / "providers",
        home=tmp_path / "home",
    )

    assert result.registry == {}
    assert result.migrated_ids == ()
    assert result.suppressed_ids == (
        "google-analytics",
        "google-tasks",
        "host-tools",
        "memory",
        "prestashop",
    )
    for manifest in result.manifests.values():
        if manifest.runtime is not None:
            assert manifest.runtime.enabled is False
            assert manifest.runtime.lifecycle_actions == {}
