from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Callable


DEFAULT_GATEWAY_READY_URL = "http://127.0.0.1:8770/ready"
_MAX_BODY_BYTES = 64 * 1024
_CACHE: dict[str, Any] = {"ts": 0.0, "url": "", "result": None}


def _minimal_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    broker = payload.get("operations_broker") or {}
    services = broker.get("services") or {}
    gateway_service = services.get("mcp_gateway") or {}
    audit = payload.get("audit") or {}

    return {
        "service_id": str(payload.get("service_id") or ""),
        "status": str(payload.get("status") or "UNKNOWN"),
        "graph_outcome": str(payload.get("graph_outcome") or "UNKNOWN"),
        "broker_available": bool(broker.get("available")),
        "gateway_service_state": str(gateway_service.get("state") or "unknown"),
        "gateway_service_health": str(gateway_service.get("health") or "unknown"),
        "audit_outcome": str(audit.get("outcome") or "UNKNOWN"),
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
    """Read the Sofia OS Gateway readiness endpoint and return minimized evidence.

    The raw readiness document contains broader operational detail. This adapter
    intentionally keeps only the fields required to establish gateway health for
    the Control Center.
    """
    try:
        request = urllib.request.Request(
            url,
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
        return {
            "ok": state == "healthy",
            "state": state,
            "text": text,
            "evidence": evidence,
        }
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
    """Return cached read-only Gateway readiness evidence for frequent UI refreshes."""
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
    """Attach one global Gateway observation only to gateway-required providers."""
    for item in payload.get("items", []):
        ident = str(item.get("id", ""))
        config = registry.get(ident, {})
        manifest = config.get("provider_manifest") or {}
        if manifest.get("gateway_required") is True:
            item["gateway_access"] = dict(evidence)
    return payload
