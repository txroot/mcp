from __future__ import annotations

from typing import Any


HEALTH_STATES = {"healthy", "degraded", "unhealthy", "unknown"}


def _layer(state: str, text: str, *, required: bool = True) -> dict[str, Any]:
    if state not in HEALTH_STATES:
        raise ValueError(f"invalid health state: {state}")
    return {"state": state, "text": text, "required": required}


def _contract(config: dict[str, Any], key: str, default: bool) -> bool:
    manifest = config.get("provider_manifest") or {}
    health = manifest.get("health_contract") or {}
    return bool(health.get(key, default))


def _process_health(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    required = _contract(config, "process_health", True)
    services = item.get("services") or []
    if not services:
        return _layer("unknown", "No managed process evidence", required=required)

    active = sum(service.get("active") == "active" for service in services)
    if active == len(services):
        return _layer("healthy", f"{active}/{len(services)} services active", required=required)
    if active:
        return _layer("degraded", f"{active}/{len(services)} services active", required=required)
    return _layer("unhealthy", "No registered service active", required=required)


def _provider_health(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    required = _contract(config, "provider_health", True)
    probe = item.get("probe") or {}
    if probe.get("ready"):
        return _layer("healthy", str(probe.get("ready_text") or "Provider ready"), required=required)
    if probe.get("live"):
        return _layer("degraded", str(probe.get("ready_text") or "Provider live but not ready"), required=required)
    if probe:
        text = probe.get("ready_text") or probe.get("live_text") or "Provider unavailable"
        return _layer("unhealthy", str(text), required=required)
    return _layer("unknown", "Provider probe not configured", required=required)


def _source_health(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    required = _contract(config, "source_health", bool(config.get("source_probe")))
    source = item.get("source_access")
    if source is None:
        source = item.get("analytics_access")
    if isinstance(source, dict):
        state = "healthy" if source.get("ok") else "unhealthy"
        return _layer(state, str(source.get("text") or "Source check completed"), required=required)
    if not required:
        return _layer("unknown", "Source health not required by contract", required=False)
    return _layer("unknown", "Source health evidence unavailable", required=True)


def _gateway_health(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    required = _contract(config, "gateway_health", bool(config.get("provider_manifest")))
    evidence = item.get("gateway_access")
    if isinstance(evidence, dict):
        state = "healthy" if evidence.get("ok") else "unhealthy"
        return _layer(state, str(evidence.get("text") or "Gateway check completed"), required=required)

    manifest = config.get("provider_manifest") or {}
    if manifest.get("gateway_required"):
        return _layer("unknown", "Gateway mediation pending evidence", required=True)
    if not required:
        return _layer("unknown", "Gateway health not declared by legacy provider", required=False)
    return _layer("unknown", "Gateway health evidence unavailable", required=True)


def apply_health_layers(
    payload: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach explicit process/provider/source/gateway health to every provider item.

    This function intentionally does not overwrite the legacy aggregate `state`.
    During migration that state remains the compatibility signal used by the current
    dashboard summary. The four health layers are evidence-oriented and may contain
    `unknown` until a real probe (not an assumption) exists.
    """
    layer_counts = {
        name: {state: 0 for state in HEALTH_STATES}
        for name in ("process", "provider", "source", "gateway")
    }

    for item in payload.get("items", []):
        ident = str(item.get("id", ""))
        config = registry.get(ident, {})
        layers = {
            "process": _process_health(item, config),
            "provider": _provider_health(item, config),
            "source": _source_health(item, config),
            "gateway": _gateway_health(item, config),
        }
        item["health_layers"] = layers
        for name, layer in layers.items():
            layer_counts[name][layer["state"]] += 1

    payload.setdefault("summary", {})["health_layers"] = layer_counts
    return payload
