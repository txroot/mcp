from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class EnforcementLevel(str, Enum):
    FULL = "FULL"
    CONTROLLED = "CONTROLLED"
    ADVISORY = "ADVISORY"
    UNSUPPORTED = "UNSUPPORTED"


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Capability:
    name: str
    enforcement: EnforcementLevel
    risks: tuple[str, ...] = ()
    requires_approval: bool = False


@dataclass(frozen=True)
class HealthContract:
    process_health: bool = True
    provider_health: bool = True
    source_health: bool = True
    gateway_health: bool = True


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    name: str
    version: str
    description: str
    capabilities: tuple[Capability, ...]
    health: HealthContract = field(default_factory=HealthContract)
    gateway_required: bool = True
    direct_external_exposure: bool = False

    def validate(self) -> None:
        errors: list[str] = []
        if not self.provider_id or not self.provider_id.startswith("provider:"):
            errors.append("provider_id must start with 'provider:'")
        if not self.name.strip():
            errors.append("name is required")
        if not self.version.strip():
            errors.append("version is required")
        if self.direct_external_exposure:
            errors.append("direct_external_exposure must be false; providers are gateway-first")
        if not self.gateway_required:
            errors.append("gateway_required must be true")

        names: set[str] = set()
        for capability in self.capabilities:
            if not capability.name.strip():
                errors.append("capability name is required")
            if capability.name in names:
                errors.append(f"duplicate capability: {capability.name}")
            names.add(capability.name)

        if errors:
            raise ValueError("; ".join(errors))

    def capability(self, name: str) -> Capability | None:
        return next((item for item in self.capabilities if item.name == name), None)


def _as_tuple(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(str(value) for value in (values or ()))


def manifest_from_dict(raw: dict[str, Any]) -> ProviderManifest:
    capabilities = tuple(
        Capability(
            name=str(item["name"]),
            enforcement=EnforcementLevel(str(item["enforcement"])),
            risks=_as_tuple(item.get("risks")),
            requires_approval=bool(item.get("requires_approval", False)),
        )
        for item in raw.get("capabilities", [])
    )

    health_raw = raw.get("health", {})
    manifest = ProviderManifest(
        provider_id=str(raw["provider_id"]),
        name=str(raw["name"]),
        version=str(raw["version"]),
        description=str(raw.get("description", "")),
        capabilities=capabilities,
        health=HealthContract(
            process_health=bool(health_raw.get("process_health", True)),
            provider_health=bool(health_raw.get("provider_health", True)),
            source_health=bool(health_raw.get("source_health", True)),
            gateway_health=bool(health_raw.get("gateway_health", True)),
        ),
        gateway_required=bool(raw.get("gateway_required", True)),
        direct_external_exposure=bool(raw.get("direct_external_exposure", False)),
    )
    manifest.validate()
    return manifest


def load_manifest(path: str | Path) -> ProviderManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("provider manifest root must be an object")
    return manifest_from_dict(raw)


def aggregate_health(states: dict[str, HealthState | str]) -> HealthState:
    normalized = {key: HealthState(value) for key, value in states.items()}
    if not normalized:
        return HealthState.UNKNOWN
    if any(value == HealthState.UNHEALTHY for value in normalized.values()):
        return HealthState.UNHEALTHY
    if any(value in {HealthState.DEGRADED, HealthState.UNKNOWN} for value in normalized.values()):
        return HealthState.DEGRADED
    return HealthState.HEALTHY
