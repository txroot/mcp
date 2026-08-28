from __future__ import annotations

from typing import Any, Callable

from sofia_runtime_inventory import RuntimeInventory


_STATUS_HEALTHY = {"ready", "healthy", "pass", "pass_read", "active", "running"}
_STATUS_DEGRADED = {"degraded", "partial", "warning"}
_STATUS_UNHEALTHY = {"unhealthy", "failed", "error", "blocked", "inactive", "stopped"}


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def classify_readiness(document: dict[str, Any]) -> tuple[str, str]:
    """Reduce a provider readiness document to a minimal, non-sensitive state."""
    if not isinstance(document, dict):
        return "unknown", "invalid readiness document"
    if document.get("ok") is False:
        return "unhealthy", "provider reported ok=false"
    if document.get("auth_ready") is False:
        return "unhealthy", "provider authentication is not ready"

    values = {
        _text(document.get("status")),
        _text(document.get("provider_status")),
        _text(document.get("health")),
        _text(document.get("outcome")),
        _text(document.get("state")),
    }
    values.discard("")
    if values & _STATUS_UNHEALTHY:
        return "unhealthy", "provider readiness failed"
    if values & _STATUS_DEGRADED:
        return "degraded", "provider readiness is degraded"
    if values & _STATUS_HEALTHY:
        return "healthy", "provider readiness passed"

    read_ready = document.get("read_ready") is True
    write_ready = document.get("write_ready") is True
    auth_ready = document.get("auth_ready") is True
    if auth_ready and (read_ready or write_ready):
        return "healthy", "provider capability readiness passed"
    if read_ready or write_ready:
        return "healthy", "provider capability readiness passed"
    return "unknown", "no recognized readiness signal"


def build_gateway_provider_inventory(
    inventory: RuntimeInventory,
    status_resolvers: dict[str, Callable[[], dict[str, Any]]],
) -> dict[str, Any]:
    """Build minimized provider inventory from explicit read-only status resolvers.

    Resolver keys are component identities in the form ``domain/component``. There is
    deliberately no dynamic tool lookup by name: deployment must wire every resolver
    explicitly, preserving the Gateway allowlist boundary.
    """
    domains: list[dict[str, Any]] = []
    healthy = degraded = unhealthy = unknown = 0

    for domain in inventory.domains:
        components: list[dict[str, Any]] = []
        for component in domain.components:
            identity = f"{domain.domain_id}/{component.component_id}"
            resolver = status_resolvers.get(identity)
            if resolver is None:
                state, detail = "unknown", "read-only status resolver not wired"
            else:
                try:
                    state, detail = classify_readiness(resolver())
                except Exception as exc:  # fail closed; never expose exception text
                    state, detail = "unhealthy", f"status resolver failed: {type(exc).__name__}"

            if state == "healthy":
                healthy += 1
            elif state == "degraded":
                degraded += 1
            elif state == "unhealthy":
                unhealthy += 1
            else:
                unknown += 1

            components.append(
                {
                    "provider_id": identity,
                    "component_id": component.component_id,
                    "role": component.role,
                    "runtime_kind": component.kind,
                    "runtime_target": component.target,
                    "gateway_exposed": component.gateway_exposed,
                    "readiness": state,
                    "readiness_detail": detail,
                    "status_contract": component.status_tool,
                    "lifecycle": {
                        "enabled": component.lifecycle_enabled,
                        "actions": [],
                    },
                }
            )
        domains.append(
            {
                "domain_id": domain.domain_id,
                "name": domain.name,
                "components": components,
            }
        )

    return {
        "inventory_id": inventory.inventory_id,
        "authority": "sofia-os-gateway",
        "mode": "read_only",
        "host": inventory.host,
        "observed_on": inventory.observed_on,
        "lifecycle_policy": inventory.lifecycle_policy,
        "summary": {
            "domains": len(domains),
            "providers": healthy + degraded + unhealthy + unknown,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "unknown": unknown,
        },
        "domains": domains,
    }


def register_gateway_provider_inventory(
    server: Any,
    *,
    annotations: Any,
    inventory: RuntimeInventory,
    status_resolvers: dict[str, Callable[[], dict[str, Any]]],
    audit: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> Callable[[], dict[str, Any]]:
    """Register the candidate ``gateway_provider_inventory`` read-only MCP tool."""

    @server.tool(title="Provider inventory/status", annotations=annotations)
    def gateway_provider_inventory() -> dict[str, Any]:
        """List canonical Sofia OS providers and minimized live readiness."""
        result = build_gateway_provider_inventory(inventory, status_resolvers)
        if audit is not None:
            audit(
                "PROVIDER_INVENTORY_READ",
                "PASS",
                {
                    "inventory_id": result["inventory_id"],
                    "domains": result["summary"]["domains"],
                    "providers": result["summary"]["providers"],
                    "external_effect": False,
                },
            )
        return result

    return gateway_provider_inventory
