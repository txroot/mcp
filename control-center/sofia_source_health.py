from __future__ import annotations

from collections.abc import Callable
from typing import Any

SourceProbe = Callable[[], dict[str, Any]]


def apply_source_health(
    payload: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    probes: dict[str, SourceProbe],
) -> dict[str, Any]:
    """Apply manifest-selected, allowlisted source-health probes to status output.

    The registry may only select a symbolic probe name. Executable code is supplied
    separately by the server-side allowlist, so a provider manifest cannot introduce
    an arbitrary command or callable.
    """
    for item in payload.get("items", []):
        ident = str(item.get("id", ""))
        config = registry.get(ident, {})
        probe_name = str(config.get("source_probe", "")).strip()
        if not probe_name:
            continue

        source_access = item.get("source_access")
        if source_access is None:
            probe = probes.get(probe_name)
            if probe is None:
                source_access = {
                    "ok": False,
                    "text": f"Source probe unavailable: {probe_name}",
                }
            else:
                try:
                    source_access = probe()
                except Exception as exc:
                    source_access = {
                        "ok": False,
                        "text": f"Source probe failed: {type(exc).__name__}",
                    }
            item["source_access"] = source_access

        source_ok = bool(source_access.get("ok"))
        item["source_health"] = "healthy" if source_ok else "unhealthy"

        tunnel_ok = bool(config.get("tunnel_configured", False))
        if not source_ok or not tunnel_ok:
            item["state"] = "degraded" if item.get("all_active") else "offline"

    return payload
