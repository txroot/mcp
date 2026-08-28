from __future__ import annotations

from typing import Any, Callable

from sofia_gateway_client import GatewayClientError, call_gateway_tool
from sofia_runtime_inventory import RuntimeInventory


_ALLOWED_STATES = {"healthy", "degraded", "unhealthy", "unknown"}


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
            provider_ids.add(provider_id)
            if str(component.get("readiness") or "") not in _ALLOWED_STATES:
                raise GatewayClientError("Provider inventory contains invalid readiness state")
            lifecycle = component.get("lifecycle") or {}
            if lifecycle.get("enabled") is not False or lifecycle.get("actions") not in ([], None):
                raise GatewayClientError("Provider lifecycle must remain disabled during reconciliation")

    if observed_domains != expected_domains:
        raise GatewayClientError("Provider inventory domain set does not match reconciled baseline")
    return document


def gateway_provider_inventory_probe(
    gateway_url: str,
    baseline: RuntimeInventory,
    *,
    call_tool: Callable[[str, str, dict[str, Any]], dict[str, Any]] = call_gateway_tool,
) -> dict[str, Any]:
    """Read live inventory from Gateway; preserve reconciled baseline on failure."""
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
            "inventory": baseline.to_dict(),
            "error": type(exc).__name__,
        }
