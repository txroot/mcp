#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


IMPORT_ANCHOR = "from .ops_client import OperationsBrokerClient\n"
IMPORT_BLOCK = """from .ops_client import OperationsBrokerClient
from .provider_inventory import register_gateway_provider_inventory
from .provider_inventory_resolvers import build_gateway_tool_resolvers
from .provider_status_client import DEFAULT_STATUS_GATEWAY_URL, ProviderStatusClient
from sofia_runtime_inventory import load_runtime_inventory
"""
RETURN_ANCHOR = "    return server\n"
REGISTRATION_BLOCK = """    provider_inventory = load_runtime_inventory(
        os.environ.get(
            \"PV_PROVIDER_INVENTORY_PATH\",
            \"/app/runtime-bundle/sofia-os-provider-inventory.json\",
        )
    )
    provider_status_client = ProviderStatusClient(
        os.environ.get(\"PV_PROVIDER_STATUS_MCP_URL\", DEFAULT_STATUS_GATEWAY_URL)
    )
    provider_status_resolvers = build_gateway_tool_resolvers(
        provider_inventory,
        provider_status_client.call,
    )
    register_gateway_provider_inventory(
        server,
        annotations=READ_ONLY_LOCAL,
        inventory=provider_inventory,
        status_resolvers=provider_status_resolvers,
        audit=_audit,
    )

"""


def _replace_once(text: str, anchor: str, replacement: str, label: str) -> str:
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"{label} anchor count must be 1, got {count}")
    return text.replace(anchor, replacement, 1)


def apply_overlay(repo_root: Path, runtime_root: Path) -> None:
    repo_root = repo_root.resolve()
    runtime_root = runtime_root.resolve()
    server_path = runtime_root / "runtime/adapters/mcp_self_hosted/server.py"
    if not server_path.is_file():
        raise FileNotFoundError(f"Gateway server.py not found: {server_path}")

    source_gateway = repo_root / "control-center/gateway"
    source_control = repo_root / "control-center"
    destination_gateway = runtime_root / "runtime/adapters/mcp_self_hosted"
    destination_bundle = runtime_root / "runtime-bundle"
    destination_gateway.mkdir(parents=True, exist_ok=True)
    destination_bundle.mkdir(parents=True, exist_ok=True)

    copies = (
        (source_gateway / "provider_inventory.py", destination_gateway / "provider_inventory.py"),
        (
            source_gateway / "provider_inventory_resolvers.py",
            destination_gateway / "provider_inventory_resolvers.py",
        ),
        (
            source_gateway / "provider_status_client.py",
            destination_gateway / "provider_status_client.py",
        ),
        (source_control / "sofia_runtime_inventory.py", runtime_root / "sofia_runtime_inventory.py"),
        (
            source_control / "runtime/sofia-os-canonical.json",
            destination_bundle / "sofia-os-provider-inventory.json",
        ),
    )
    for source, destination in copies:
        if not source.is_file():
            raise FileNotFoundError(f"overlay source missing: {source}")
        shutil.copy2(source, destination)

    original = server_path.read_text(encoding="utf-8")
    if "register_gateway_provider_inventory" in original:
        raise RuntimeError("provider inventory overlay already present")
    updated = _replace_once(original, IMPORT_ANCHOR, IMPORT_BLOCK, "import")
    updated = _replace_once(
        updated,
        RETURN_ANCHOR,
        REGISTRATION_BLOCK + RETURN_ANCHOR,
        "return server",
    )
    server_path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Sofia provider-inventory canary overlay")
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    args = parser.parse_args()
    apply_overlay(args.repo_root, args.runtime_root)
    print("SOFIA_PROVIDER_INVENTORY_OVERLAY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
