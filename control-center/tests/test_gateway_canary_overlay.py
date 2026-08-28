from pathlib import Path

import pytest

from gateway.canary.apply_overlay import apply_overlay


ROOT = Path(__file__).resolve().parents[2]


def _runtime_fixture(tmp_path: Path, server_text: str | None = None) -> Path:
    runtime = tmp_path / "app"
    target = runtime / "runtime/adapters/mcp_self_hosted"
    target.mkdir(parents=True)
    (runtime / "runtime-bundle").mkdir(parents=True)
    if server_text is None:
        server_text = """from __future__ import annotations
import os
from .ops_client import OperationsBrokerClient

READ_ONLY_LOCAL = object()

def create_mcp_server():
    server = object()
    def _audit(event_type, outcome, metadata):
        return None
    return server
"""
    (target / "server.py").write_text(server_text, encoding="utf-8")
    return runtime


def test_overlay_copies_candidate_modules_and_patches_gateway_server(tmp_path: Path):
    runtime = _runtime_fixture(tmp_path)

    apply_overlay(ROOT, runtime)

    server = (runtime / "runtime/adapters/mcp_self_hosted/server.py").read_text(encoding="utf-8")
    assert "register_gateway_provider_inventory" in server
    assert "build_gateway_tool_resolvers" in server
    assert "ProviderStatusClient" in server
    assert "PV_PROVIDER_STATUS_MCP_URL" in server
    assert "annotations=READ_ONLY_LOCAL" in server
    assert server.index("register_gateway_provider_inventory(") < server.index("    return server")

    assert (runtime / "runtime/adapters/mcp_self_hosted/provider_inventory.py").is_file()
    assert (runtime / "runtime/adapters/mcp_self_hosted/provider_inventory_resolvers.py").is_file()
    assert (runtime / "runtime/adapters/mcp_self_hosted/provider_status_client.py").is_file()
    assert (runtime / "runtime/adapters/mcp_self_hosted/provider_inventory_smoke.py").is_file()
    assert (runtime / "sofia_runtime_inventory.py").is_file()
    assert (runtime / "runtime-bundle/sofia-os-provider-inventory.json").is_file()


def test_overlay_is_not_reentrant(tmp_path: Path):
    runtime = _runtime_fixture(tmp_path)
    apply_overlay(ROOT, runtime)

    with pytest.raises(RuntimeError, match="already present"):
        apply_overlay(ROOT, runtime)


def test_overlay_fails_closed_when_gateway_server_shape_changes(tmp_path: Path):
    runtime = _runtime_fixture(
        tmp_path,
        server_text="from __future__ import annotations\n\ndef create_mcp_server():\n    return object()\n",
    )

    with pytest.raises(RuntimeError, match="import anchor count"):
        apply_overlay(ROOT, runtime)
