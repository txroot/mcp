#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

import server as legacy
from sofia_gateway_client import DEFAULT_GATEWAY_MCP_URL, GatewayClientError
from sofia_gateway_health import (
    DEFAULT_GATEWAY_READY_URL,
    apply_gateway_evidence,
    gateway_health_probe,
)
from sofia_health import apply_health_layers
from sofia_lifecycle import LifecycleController, apply_lifecycle_availability
from sofia_registry import load_control_center_registry
from sofia_source_health import apply_source_health
from sofia_ui import upgrade_control_center_html

PROVIDERS_DIR = Path(__file__).with_name("providers")
GATEWAY_READY_URL = os.environ.get("SOFIA_GATEWAY_READY_URL", DEFAULT_GATEWAY_READY_URL).strip()
GATEWAY_MCP_URL = os.environ.get("SOFIA_GATEWAY_MCP_URL", DEFAULT_GATEWAY_MCP_URL).strip()
REGISTRY_LOAD = load_control_center_registry(
    legacy_registry=legacy.MCP_REGISTRY,
    providers_dir=PROVIDERS_DIR,
    home=legacy.HOME,
)
legacy.MCP_REGISTRY = REGISTRY_LOAD.registry
legacy.SAFE_UNITS = {
    unit
    for config in legacy.MCP_REGISTRY.values()
    for unit in config.get("services", [])
}
legacy.PROVIDER_MANIFESTS = REGISTRY_LOAD.manifests
legacy.PROVIDER_MIGRATED_IDS = REGISTRY_LOAD.migrated_ids
legacy.PROVIDER_MANIFEST_SOURCES = REGISTRY_LOAD.sources

_SOURCE_PROBES = {
    "google_analytics": legacy.analytics_data_probe,
    "prestashop": legacy.prestashop_data_probe,
}
_LEGACY_STATUS_PAYLOAD = legacy.status_payload
LIFECYCLE = LifecycleController(legacy.MCP_REGISTRY, GATEWAY_MCP_URL)


def _manifest_status_payload():
    payload = _LEGACY_STATUS_PAYLOAD()
    payload = apply_source_health(
        payload=payload,
        registry=legacy.MCP_REGISTRY,
        probes=_SOURCE_PROBES,
    )
    gateway_evidence = gateway_health_probe(GATEWAY_READY_URL)
    payload = apply_gateway_evidence(
        payload=payload,
        registry=legacy.MCP_REGISTRY,
        evidence=gateway_evidence,
    )
    payload = apply_lifecycle_availability(
        payload=payload,
        registry=legacy.MCP_REGISTRY,
        gateway_evidence=gateway_evidence,
    )
    return apply_health_layers(
        payload=payload,
        registry=legacy.MCP_REGISTRY,
    )


def _direct_lifecycle_disabled(_ident: str, _action: str) -> tuple[bool, str]:
    return False, "Direct lifecycle is disabled; use Sofia OS Gateway mediation."


class SofiaHandler(legacy.Handler):
    """Control Center handler with lifecycle authority removed from the legacy path."""

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0 or length > 4096:
            raise ValueError("request body exceeds lifecycle limit")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("request body must be an object")
        return data

    def do_POST(self):
        if self.path == "/api/action":
            self._json(
                {
                    "ok": False,
                    "message": "Legacy direct lifecycle endpoint is disabled; use Gateway-mediated lifecycle.",
                },
                410,
            )
            return
        if self.path not in {"/api/lifecycle/prepare", "/api/lifecycle/execute"}:
            super().do_POST()
            return
        if not self._authorized():
            self._json({"ok": False, "message": "unauthorized"}, 403)
            return
        try:
            data = self._read_json_body()
            if self.path == "/api/lifecycle/prepare":
                result = LIFECYCLE.prepare(
                    str(data.get("id") or ""),
                    str(data.get("action") or ""),
                )
                self._json(result, 200 if result.get("ok") else 409)
                return
            result = LIFECYCLE.execute(
                str(data.get("approval_id") or ""),
                str(data.get("confirmation") or ""),
            )
            self._json(result, 200)
        except ValueError as exc:
            self._json({"ok": False, "message": legacy.redact(str(exc))}, 400)
        except PermissionError as exc:
            self._json({"ok": False, "message": legacy.redact(str(exc))}, 403)
        except GatewayClientError as exc:
            self._json({"ok": False, "message": legacy.redact(str(exc))}, 503)
        except Exception as exc:
            self._json({"ok": False, "message": legacy.redact(str(exc))}, 500)


legacy.status_payload = _manifest_status_payload
legacy.service_action = _direct_lifecycle_disabled
legacy.HTML = upgrade_control_center_html(legacy.HTML)

if __name__ == "__main__":
    migrated = ",".join(REGISTRY_LOAD.migrated_ids) or "none"
    print(
        f"Sofia Control Center listening on http://{legacy.HOST}:{legacy.PORT} "
        f"manifest_migrated={migrated} gateway_ready={GATEWAY_READY_URL} "
        f"gateway_mcp={GATEWAY_MCP_URL} lifecycle=gateway-only",
        flush=True,
    )
    legacy.ThreadingHTTPServer((legacy.HOST, legacy.PORT), SofiaHandler).serve_forever()
