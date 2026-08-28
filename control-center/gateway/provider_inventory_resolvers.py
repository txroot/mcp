from __future__ import annotations

from typing import Any, Callable

from sofia_runtime_inventory import RuntimeInventory


# Static mapping from canonical component identity to an already-existing read-only
# Gateway status tool. There is deliberately no dynamic lookup from inventory text.
_CANONICAL_STATUS_TOOLS = {
    "sofia-core/gateway": "gateway_health",
    "sofia-core/operations-broker": "gateway_vm_status",
    "sofia-core/secure-tunnel": "gateway_vm_status",
    "ssh/ssh-provider": "shell_status",
    "pc-edge/pc-edge-provider": "pc.health",
    "prestashop/store-readonly": "prestashop.health",
    "prestashop/sofiabridge-readonly": "prestashop.bridge.status",
    "prestashop/catalog-status-write": "prestashop.catalog_status.status",
    "prestashop/category-writer": "prestashop.category_writer.status",
    "prestashop/seo-write": "prestashop.seo.write.status",
    "mail/read": "mail.read.status",
    "mail/modify": "mail.modify.status",
    "mail/draft": "mail.draft.status",
    "mail/send": "mail.send.status",
    "calendar/read": "calendar.read.status",
    "calendar/write": "calendar.write.status",
    "tasks/read": "gateway_external_services_status",
    "tasks/write": "gateway_tasks_write_status",
    "sheets/read": "sheets.read.status",
    "sheets/write": "sheets.write.status",
    "contacts/read": "contacts.read.status",
    "drive/read": "drive.read.status",
    "location/read": "location.read.status",
    "elektro3/catalog-read": "elektro3.read.status",
}

# Components intentionally omitted because there is no canonical Gateway status tool
# yet. They remain UNKNOWN rather than being inferred from process/container presence.
_INTENTIONALLY_UNRESOLVED = {
    "prestashop/product-description-write",
    "trello/readwrite",
}


def canonical_status_tools() -> dict[str, str]:
    return dict(_CANONICAL_STATUS_TOOLS)


def intentionally_unresolved_components() -> tuple[str, ...]:
    return tuple(sorted(_INTENTIONALLY_UNRESOLVED))


def _inventory_components(inventory: RuntimeInventory) -> dict[str, Any]:
    return {
        f"{domain.domain_id}/{component.component_id}": component
        for domain in inventory.domains
        for component in domain.components
    }


def validate_resolver_contract(inventory: RuntimeInventory) -> None:
    components = _inventory_components(inventory)
    declared = set(_CANONICAL_STATUS_TOOLS) | _INTENTIONALLY_UNRESOLVED
    if declared != set(components):
        missing = sorted(set(components) - declared)
        extra = sorted(declared - set(components))
        raise ValueError(
            "provider resolver map does not match canonical inventory: "
            f"missing={missing} extra={extra}"
        )

    for identity, tool_name in _CANONICAL_STATUS_TOOLS.items():
        component = components[identity]
        if component.status_tool != tool_name:
            raise ValueError(
                f"status contract mismatch for {identity}: "
                f"inventory={component.status_tool!r} resolver={tool_name!r}"
            )
        if not component.gateway_exposed:
            raise ValueError(f"resolver cannot target non-exposed provider: {identity}")
        if component.lifecycle_enabled:
            raise ValueError(f"resolver inventory cannot enable lifecycle: {identity}")

    for identity in _INTENTIONALLY_UNRESOLVED:
        component = components[identity]
        if component.status_tool is not None:
            raise ValueError(
                f"intentionally unresolved component unexpectedly has status contract: {identity}"
            )


def build_gateway_tool_resolvers(
    inventory: RuntimeInventory,
    call_status_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Callable[[], dict[str, Any]]]:
    """Bind canonical components to explicit read-only Gateway status calls."""
    validate_resolver_contract(inventory)
    resolvers: dict[str, Callable[[], dict[str, Any]]] = {}
    for identity, tool_name in _CANONICAL_STATUS_TOOLS.items():
        resolvers[identity] = (
            lambda tool_name=tool_name: call_status_tool(tool_name, {})
        )
    return resolvers
