from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sofia_provider import ProviderManifest, load_manifest


@dataclass(frozen=True)
class RegistryLoadResult:
    registry: dict[str, dict[str, Any]]
    manifests: dict[str, ProviderManifest]
    migrated_ids: tuple[str, ...]
    sources: dict[str, str]


def _expand(value: Any, home: Path) -> Any:
    if isinstance(value, str):
        return value.replace("${HOME}", str(home))
    if isinstance(value, list):
        return [_expand(item, home) for item in value]
    if isinstance(value, dict):
        return {str(key): _expand(item, home) for key, item in value.items()}
    return value


def _runtime_to_legacy_config(manifest: ProviderManifest, home: Path, source: Path) -> tuple[str, dict[str, Any]]:
    runtime = manifest.runtime
    if runtime is None:
        raise ValueError(f"{source.name}: runtime section is required for registry migration")

    config: dict[str, Any] = {
        "name": manifest.name,
        "description": manifest.description,
        "services": list(runtime.services),
        "profile": runtime.profile,
        "mcp": runtime.mcp,
        "health": runtime.health_endpoint,
        "admin": runtime.admin,
        "kind": runtime.kind,
        "tunnel_configured": runtime.tunnel_configured,
        "probe_type": runtime.probe_type,
        "source_probe": runtime.source_probe,
        "lifecycle_actions": dict(runtime.lifecycle_actions or {}),
        "provider_manifest": {
            "provider_id": manifest.provider_id,
            "version": manifest.version,
            "gateway_required": manifest.gateway_required,
            "direct_external_exposure": manifest.direct_external_exposure,
            "capabilities": [
                {
                    "name": capability.name,
                    "enforcement": capability.enforcement.value,
                    "risks": list(capability.risks),
                    "requires_approval": capability.requires_approval,
                }
                for capability in manifest.capabilities
            ],
            "health_contract": {
                "process_health": manifest.health.process_health,
                "provider_health": manifest.health.provider_health,
                "source_health": manifest.health.source_health,
                "gateway_health": manifest.health.gateway_health,
            },
            "source": str(source),
        },
    }
    if runtime.tools_probe:
        config["tools_probe"] = _expand(runtime.tools_probe, home)
    return runtime.registry_id, _expand(config, home)


def load_control_center_registry(
    legacy_registry: dict[str, dict[str, Any]],
    providers_dir: str | Path,
    home: str | Path,
) -> RegistryLoadResult:
    providers_path = Path(providers_dir)
    home_path = Path(home)
    registry = copy.deepcopy(legacy_registry)
    manifests: dict[str, ProviderManifest] = {}
    sources: dict[str, str] = {}
    migrated_ids: list[str] = []
    runtime_ids: set[str] = set()

    if not providers_path.exists():
        return RegistryLoadResult(registry, manifests, tuple(), sources)

    for path in sorted(providers_path.glob("*.provider.json")):
        manifest = load_manifest(path)
        if manifest.provider_id in manifests:
            raise ValueError(f"duplicate provider_id: {manifest.provider_id}")
        manifests[manifest.provider_id] = manifest
        sources[manifest.provider_id] = str(path)

        if manifest.runtime is None:
            continue
        registry_id, config = _runtime_to_legacy_config(manifest, home_path, path)
        if registry_id in runtime_ids:
            raise ValueError(f"duplicate runtime.registry_id: {registry_id}")
        runtime_ids.add(registry_id)
        registry[registry_id] = config
        migrated_ids.append(registry_id)

    return RegistryLoadResult(
        registry=registry,
        manifests=manifests,
        migrated_ids=tuple(migrated_ids),
        sources=sources,
    )
