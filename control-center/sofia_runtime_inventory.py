from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_ALLOWED_KINDS = {"docker", "systemd", "remote"}
_ALLOWED_ROLES = {
    "gateway",
    "operations_broker",
    "secure_tunnel",
    "privileged_provider",
    "controlled_pc_provider",
    "read",
    "controlled_write",
    "controlled_readwrite",
}


@dataclass(frozen=True)
class RuntimeComponent:
    component_id: str
    role: str
    kind: str
    target: str
    status_tool: str | None
    gateway_exposed: bool
    lifecycle_enabled: bool
    note: str = ""


@dataclass(frozen=True)
class RuntimeDomain:
    domain_id: str
    name: str
    components: tuple[RuntimeComponent, ...]


@dataclass(frozen=True)
class RuntimeInventory:
    inventory_id: str
    host: str
    observed_on: str
    authority: str
    lifecycle_policy: str
    domains: tuple[RuntimeDomain, ...]
    excluded_legacy_registry_ids: tuple[str, ...]
    excluded_noncanonical_runtime_classes: tuple[str, ...]

    def validate(self) -> None:
        errors: list[str] = []
        if not self.inventory_id.strip():
            errors.append("inventory_id is required")
        if not self.host.strip():
            errors.append("host is required")
        if self.authority != "runtime-reconciled":
            errors.append("authority must be runtime-reconciled")
        if self.lifecycle_policy != "disabled_until_gateway_provider_inventory":
            errors.append("lifecycle_policy must remain fail-closed during reconciliation")

        domain_ids: set[str] = set()
        global_targets: set[str] = set()
        for domain in self.domains:
            if not domain.domain_id.strip() or not domain.name.strip():
                errors.append("domain id and name are required")
                continue
            if domain.domain_id in domain_ids:
                errors.append(f"duplicate domain_id: {domain.domain_id}")
            domain_ids.add(domain.domain_id)
            if not domain.components:
                errors.append(f"domain {domain.domain_id} must contain components")

            component_ids: set[str] = set()
            for component in domain.components:
                if not component.component_id.strip():
                    errors.append(f"domain {domain.domain_id} has empty component_id")
                if component.component_id in component_ids:
                    errors.append(
                        f"duplicate component_id in {domain.domain_id}: {component.component_id}"
                    )
                component_ids.add(component.component_id)
                if component.kind not in _ALLOWED_KINDS:
                    errors.append(f"unsupported runtime kind: {component.kind}")
                if component.role not in _ALLOWED_ROLES:
                    errors.append(f"unsupported runtime role: {component.role}")
                if not component.target.strip():
                    errors.append(f"component {domain.domain_id}/{component.component_id} target is required")
                if component.target in global_targets:
                    errors.append(f"runtime target reused across domains: {component.target}")
                global_targets.add(component.target)
                if component.status_tool is not None and not component.status_tool.strip():
                    errors.append("status_tool must be null or non-empty")
                if component.lifecycle_enabled:
                    errors.append(
                        f"lifecycle must remain disabled during reconciliation: {domain.domain_id}/{component.component_id}"
                    )

        required_domains = {
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
        missing = sorted(required_domains - domain_ids)
        if missing:
            errors.append("missing canonical domains: " + ",".join(missing))

        forbidden_domains = {"memory", "google-analytics", "host-tools"}
        present_forbidden = sorted(forbidden_domains & domain_ids)
        if present_forbidden:
            errors.append("obsolete domains present: " + ",".join(present_forbidden))

        expected_suppressed = {"host-tools", "google-tasks", "memory", "google-analytics", "prestashop"}
        if set(self.excluded_legacy_registry_ids) != expected_suppressed:
            errors.append("excluded_legacy_registry_ids does not match reconciled legacy registry")

        if errors:
            raise ValueError("; ".join(errors))

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_id": self.inventory_id,
            "host": self.host,
            "observed_on": self.observed_on,
            "authority": self.authority,
            "lifecycle_policy": self.lifecycle_policy,
            "domains": [
                {
                    "domain_id": domain.domain_id,
                    "name": domain.name,
                    "components": [
                        {
                            "component_id": component.component_id,
                            "role": component.role,
                            "kind": component.kind,
                            "target": component.target,
                            "status_tool": component.status_tool,
                            "gateway_exposed": component.gateway_exposed,
                            "lifecycle_enabled": component.lifecycle_enabled,
                            **({"note": component.note} if component.note else {}),
                        }
                        for component in domain.components
                    ],
                }
                for domain in self.domains
            ],
            "excluded_legacy_registry_ids": list(self.excluded_legacy_registry_ids),
            "excluded_noncanonical_runtime_classes": list(self.excluded_noncanonical_runtime_classes),
        }


def _component_from_dict(raw: dict[str, Any]) -> RuntimeComponent:
    return RuntimeComponent(
        component_id=str(raw["component_id"]),
        role=str(raw["role"]),
        kind=str(raw["kind"]),
        target=str(raw["target"]),
        status_tool=(None if raw.get("status_tool") is None else str(raw.get("status_tool"))),
        gateway_exposed=bool(raw.get("gateway_exposed", False)),
        lifecycle_enabled=bool(raw.get("lifecycle_enabled", False)),
        note=str(raw.get("note", "")),
    )


def inventory_from_dict(raw: dict[str, Any]) -> RuntimeInventory:
    domains = tuple(
        RuntimeDomain(
            domain_id=str(domain["domain_id"]),
            name=str(domain["name"]),
            components=tuple(_component_from_dict(item) for item in domain.get("components", [])),
        )
        for domain in raw.get("domains", [])
    )
    inventory = RuntimeInventory(
        inventory_id=str(raw["inventory_id"]),
        host=str(raw["host"]),
        observed_on=str(raw["observed_on"]),
        authority=str(raw["authority"]),
        lifecycle_policy=str(raw["lifecycle_policy"]),
        domains=domains,
        excluded_legacy_registry_ids=tuple(str(item) for item in raw.get("excluded_legacy_registry_ids", [])),
        excluded_noncanonical_runtime_classes=tuple(
            str(item) for item in raw.get("excluded_noncanonical_runtime_classes", [])
        ),
    )
    inventory.validate()
    return inventory


def load_runtime_inventory(path: str | Path) -> RuntimeInventory:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("runtime inventory root must be an object")
    return inventory_from_dict(raw)
