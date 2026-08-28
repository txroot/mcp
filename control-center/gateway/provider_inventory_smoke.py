#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

from .provider_inventory import build_gateway_provider_inventory
from .provider_inventory_resolvers import (
    build_gateway_tool_resolvers,
    intentionally_unresolved_components,
)
from .provider_status_client import DEFAULT_STATUS_GATEWAY_URL, ProviderStatusClient
from sofia_runtime_inventory import load_runtime_inventory


DEFAULT_INVENTORY_PATH = "/app/runtime-bundle/sofia-os-provider-inventory.json"


def main() -> int:
    inventory = load_runtime_inventory(
        Path(os.environ.get("PV_PROVIDER_INVENTORY_PATH", DEFAULT_INVENTORY_PATH))
    )
    client = ProviderStatusClient(
        os.environ.get("PV_PROVIDER_STATUS_MCP_URL", DEFAULT_STATUS_GATEWAY_URL)
    )
    resolvers = build_gateway_tool_resolvers(inventory, client.call)
    result = build_gateway_provider_inventory(inventory, resolvers)

    summary = result["summary"]
    if summary["domains"] != 13:
        raise RuntimeError("canary domain count mismatch")
    if summary["providers"] != 26:
        raise RuntimeError("canary provider count mismatch")
    if len(resolvers) != 24:
        raise RuntimeError("canary resolver count mismatch")
    if any(
        component["lifecycle"] != {"enabled": False, "actions": []}
        for domain in result["domains"]
        for component in domain["components"]
    ):
        raise RuntimeError("canary lifecycle must remain disabled")

    print(
        json.dumps(
            {
                "outcome": "PASS",
                "inventory_id": result["inventory_id"],
                "authority": result["authority"],
                "mode": result["mode"],
                "summary": summary,
                "resolved": len(resolvers),
                "intentionally_unresolved": list(intentionally_unresolved_components()),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
