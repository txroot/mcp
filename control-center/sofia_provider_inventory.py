from __future__ import annotations

from typing import Any, Callable

from sofia_gateway_client import GatewayClientError, call_gateway_tool
from sofia_runtime_inventory import RuntimeInventory


_ALLOWED_STATES = {"healthy", "degraded", "unhealthy", "unknown"}


def _baseline_view(baseline: RuntimeInventory) -> dict[str, Any]:
    domains: list[dict[str, Any]] = []
    provider_count = 0
    for domain in baseline.domains:
        components: list[dict[str, Any]] = []
        for component in domain.components:
            provider_count += 1
            components.append(
                {
                    "provider_id": f"{domain.domain_id}/{component.component_id}",
                    "component_id": component.component_id,
                    "role": component.role,
                    "runtime_kind": component.kind,
                    "runtime_target": component.target,
                    "gateway_exposed": component.gateway_exposed,
                    "readiness": "unknown",
                    "readiness_detail": "live Gateway provider inventory unavailable",
                    "status_contract": component.status_tool,
                    "lifecycle": {"enabled": False, "actions": []},
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
        "inventory_id": baseline.inventory_id,
        "authority": "reconciled-baseline",
        "mode": "read_only",
        "host": baseline.host,
        "observed_on": baseline.observed_on,
        "lifecycle_policy": baseline.lifecycle_policy,
        "summary": {
            "domains": len(domains),
            "providers": provider_count,
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "unknown": provider_count,
        },
        "domains": domains,
    }


def _validate_live_inventory(document: dict[str, Any], expected: RuntimeInventory) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise GatewayClientError("Provider inventory response must be an object")
    if document.get("inventory_id") != expected.inventory_id:
        raise GatewayClientError("Provider inventory identity does not match reconciled baseline")
    if document.get("authority") != "sofia-os-gateway":
        raise GatewayClientError("Provider inventory authority is invalid")
    if document.get("mode") != "read_only":
        raise GatewayClientError("Provider inventory must be read-only")
    if document.get("host") != expected.host:
        raise GatewayClientError("Provider inventory host does not match reconciled baseline")
    domains = document.get("domains")
    if not isinstance(domains, list):
        raise GatewayClientError("Provider inventory domains are missing")

    expected_domains = {domain.domain_id for domain in expected.domains}
    expected_components = {
        f"{domain.domain_id}/{component.component_id}": component
        for domain in expected.domains
        for component in domain.components
    }
    observed_domains: set[str] = set()
    provider_ids: set[str] = set()
    for domain in domains:
        if not isinstance(domain, dict):
            raise GatewayClientError("Provider inventory domain must be an object")
        domain_id = str(domain.get("domain_id") or "")
        if not domain_id or domain_id in observed_domains:
            raise GatewayClientError("Provider inventory contains invalid domain identity")
        observed_domains.add(domain_id)
        components = domain.get("components")
        if not isinstance(components, list):
            raise GatewayClientError("Provider inventory components are missing")
        for component in components:
            if not isinstance(component, dict):
                raise GatewayClientError("Provider inventory component must be an object")
            provider_id = str(component.get("provider_id") or "")
            if not provider_id.startswith(domain_id + "/") or provider_id in provider_ids:
                raise GatewayClientError("Provider inventory contains invalid provider identity")
            expected_component = expected_components.get(provider_id)
            if expected_component is None:
                raise GatewayClientError("Provider inventory contains an unknown provider")
            provider_ids.add(provider_id)
            if str(component.get("component_id") or "") != expected_component.component_id:
                raise GatewayClientError("Provider component identity changed")
            if str(component.get("role") or "") != expected_component.role:
                raise GatewayClientError("Provider role changed")
            if str(component.get("runtime_kind") or "") != expected_component.kind:
                raise GatewayClientError("Provider runtime kind changed")
            if str(component.get("runtime_target") or "") != expected_component.target:
                raise GatewayClientError("Provider runtime target changed")
            if component.get("gateway_exposed") is not expected_component.gateway_exposed:
                raise GatewayClientError("Provider Gateway exposure changed")
            if component.get("status_contract") != expected_component.status_tool:
                raise GatewayClientError("Provider status contract changed")
            if str(component.get("readiness") or "") not in _ALLOWED_STATES:
                raise GatewayClientError("Provider inventory contains invalid readiness state")
            lifecycle = component.get("lifecycle") or {}
            if lifecycle.get("enabled") is not False or lifecycle.get("actions") not in ([], None):
                raise GatewayClientError("Provider lifecycle must remain disabled during reconciliation")

    if observed_domains != expected_domains:
        raise GatewayClientError("Provider inventory domain set does not match reconciled baseline")
    if provider_ids != set(expected_components):
        raise GatewayClientError("Provider inventory component set does not match reconciled baseline")
    return document


def gateway_provider_inventory_probe(
    gateway_url: str,
    baseline: RuntimeInventory,
    *,
    call_tool: Callable[[str, str, dict[str, Any]], dict[str, Any]] = call_gateway_tool,
) -> dict[str, Any]:
    """Read live inventory from Gateway; preserve identical baseline shape on failure."""
    try:
        live = call_tool(gateway_url, "gateway_provider_inventory", {})
        validated = _validate_live_inventory(live, baseline)
        return {
            "source": "gateway_live",
            "live": True,
            "inventory": validated,
            "error": None,
        }
    except (GatewayClientError, ValueError, TypeError, KeyError) as exc:
        return {
            "source": "reconciled_baseline",
            "live": False,
            "inventory": _baseline_view(baseline),
            "error": type(exc).__name__,
        }
