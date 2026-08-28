from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse


DEFAULT_GATEWAY_READY_URL = "http://127.0.0.1:8770/ready"
_MAX_BODY_BYTES = 64 * 1024
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CACHE: dict[str, Any] = {"ts": 0.0, "url": "", "result": None}


def validate_gateway_ready_url(url: str) -> str:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid Gateway readiness port") from exc
    if parsed.scheme != "http":
        raise ValueError("Gateway readiness scheme must be http")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("Gateway readiness host must be loopback")
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Gateway readiness URL must include a valid port")
    if parsed.path != "/ready" or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Gateway readiness path must be exactly /ready")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Gateway readiness URL cannot contain credentials")
    return url


def _minimal_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    broker = payload.get("operations_broker") or {}
    services = broker.get("services") or {}
    gateway_service = services.get("mcp_gateway") or {}
    audit = payload.get("audit") or {}
    lifecycle_actions = sorted(
        str(action)
        for action in (broker.get("allowed_actions") or [])
        if str(action).startswith("provider.")
    )
    return {
        "service_id": str(payload.get("service_id") or ""),
        "status": str(payload.get("status") or "UNKNOWN"),
        "graph_outcome": str(payload.get("graph_outcome") or "UNKNOWN"),
        "broker_available": bool(broker.get("available")),
        "gateway_service_state": str(gateway_service.get("state") or "unknown"),
        "gateway_service_health": str(gateway_service.get("health") or "unknown"),
        "audit_outcome": str(audit.get("outcome") or "UNKNOWN"),
        "provider_lifecycle_actions": lifecycle_actions,
    }


def _classify(evidence: dict[str, Any]) -> tuple[str, str]:
    status = evidence["status"]
    graph = evidence["graph_outcome"]
    broker_available = evidence["broker_available"]
    service_state = evidence["gateway_service_state"]
    service_health = evidence["gateway_service_health"]
    audit = evidence["audit_outcome"]
    if status != "READY" or service_state != "running" or service_health != "healthy":
        state = "unhealthy"
    elif graph != "PASS" or not broker_available or audit != "PASS":
        state = "degraded"
    else:
        state = "healthy"
    text = (
        f"Gateway {status} · graph {graph} · "
        f"broker {'ready' if broker_available else 'unavailable'} · audit {audit}"
    )
    return state, text


def probe_gateway_ready(
    url: str = DEFAULT_GATEWAY_READY_URL,
    *,
    timeout: float = 1.5,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    try:
        validated_url = validate_gateway_ready_url(url)
        request = urllib.request.Request(
            validated_url,
            headers={"User-Agent": "sofia-control-center/1"},
            method="GET",
        )
        with opener(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 200))
            body = response.read(_MAX_BODY_BYTES + 1)
        if len(body) > _MAX_BODY_BYTES:
            raise ValueError("gateway readiness response exceeds size limit")
        if not 200 <= status_code < 300:
            raise RuntimeError(f"gateway readiness HTTP {status_code}")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("gateway readiness response must be an object")
        evidence = _minimal_evidence(payload)
        state, text = _classify(evidence)
        return {"ok": state == "healthy", "state": state, "text": text, "evidence": evidence}
    except Exception as exc:
        return {
            "ok": False,
            "state": "unhealthy",
            "text": f"Gateway readiness probe failed: {type(exc).__name__}",
            "evidence": {},
        }


def gateway_health_probe(
    url: str = DEFAULT_GATEWAY_READY_URL,
    *,
    max_age: float = 4.0,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    current = now()
    cached = _CACHE.get("result")
    if cached is not None and _CACHE.get("url") == url and current - float(_CACHE.get("ts", 0.0)) < max_age:
        return dict(cached)
    result = probe_gateway_ready(url)
    _CACHE.update({"ts": current, "url": url, "result": dict(result)})
    return result


def apply_gateway_evidence(
    payload: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    for item in payload.get("items", []):
        ident = str(item.get("id", ""))
        config = registry.get(ident, {})
        manifest = config.get("provider_manifest") or {}
        if manifest.get("gateway_required") is True:
            item["gateway_access"] = dict(evidence)
    return payload
