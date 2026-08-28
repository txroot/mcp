#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import server as legacy
from sofia_gateway_health import (
    DEFAULT_GATEWAY_READY_URL,
    apply_gateway_evidence,
    gateway_health_probe,
)
from sofia_health import apply_health_layers
from sofia_registry import load_control_center_registry
from sofia_source_health import apply_source_health
from sofia_ui import upgrade_control_center_html

PROVIDERS_DIR = Path(__file__).with_name("providers")
GATEWAY_READY_URL = os.environ.get("SOFIA_GATEWAY_READY_URL", DEFAULT_GATEWAY_READY_URL).strip()
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


def _manifest_status_payload():
    payload = _LEGACY_STATUS_PAYLOAD()
    payload = apply_source_health(
        payload=payload,
        registry=legacy.MCP_REGISTRY,
        probes=_SOURCE_PROBES,
    )
    payload = apply_gateway_evidence(
        payload=payload,
        registry=legacy.MCP_REGISTRY,
        evidence=gateway_health_probe(GATEWAY_READY_URL),
    )
    return apply_health_layers(
        payload=payload,
        registry=legacy.MCP_REGISTRY,
    )


legacy.status_payload = _manifest_status_payload
legacy.HTML = upgrade_control_center_html(legacy.HTML)

if __name__ == "__main__":
    migrated = ",".join(REGISTRY_LOAD.migrated_ids) or "none"
    print(
        f"Sofia Control Center listening on http://{legacy.HOST}:{legacy.PORT} "
        f"manifest_migrated={migrated} gateway_ready={GATEWAY_READY_URL}",
        flush=True,
    )
    legacy.ThreadingHTTPServer((legacy.HOST, legacy.PORT), legacy.Handler).serve_forever()
