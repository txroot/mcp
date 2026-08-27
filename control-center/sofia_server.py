#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import server as legacy
from sofia_registry import load_control_center_registry

PROVIDERS_DIR = Path(__file__).with_name("providers")
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

if __name__ == "__main__":
    migrated = ",".join(REGISTRY_LOAD.migrated_ids) or "none"
    print(
        f"Sofia Control Center listening on http://{legacy.HOST}:{legacy.PORT} "
        f"manifest_migrated={migrated}",
        flush=True,
    )
    legacy.ThreadingHTTPServer((legacy.HOST, legacy.PORT), legacy.Handler).serve_forever()
