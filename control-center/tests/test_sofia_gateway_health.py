import json

from sofia_gateway_health import (
    apply_gateway_evidence,
    probe_gateway_ready,
    validate_gateway_ready_url,
)
from sofia_health import apply_health_layers


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self._body[:size]


def opener_for(payload, status=200):
    def _open(request, timeout=0):
        assert request.full_url == "http://127.0.0.1:8770/ready"
        assert timeout == 1.5
        return FakeResponse(payload, status=status)
    return _open


def gateway_payload(**overrides):
    payload = {
        "service_id": "service:pedrovault-gateway/phase4",
        "status": "READY",
        "graph_outcome": "PASS",
        "operations_broker": {
            "available": True,
            "allowed_actions": [
                "backup.create",
                "provider.memory.restart",
                "provider.prestashop.stop",
            ],
            "services": {
                "mcp_gateway": {"state": "running", "health": "healthy"},
            },
        },
        "audit": {"outcome": "PASS", "last_event_hash": "do-not-copy"},
        "offhost_backup": {"remote_paths": ["sensitive/path"]},
        "live_vault": {"root": "/srv/private"},
    }
    payload.update(overrides)
    return payload


def test_ready_gateway_is_healthy_and_evidence_is_minimized():
    result = probe_gateway_ready(opener=opener_for(gateway_payload()))

    assert result["ok"] is True
    assert result["state"] == "healthy"
    assert result["evidence"] == {
        "service_id": "service:pedrovault-gateway/phase4",
        "status": "READY",
        "graph_outcome": "PASS",
        "broker_available": True,
        "gateway_service_state": "running",
        "gateway_service_health": "healthy",
        "audit_outcome": "PASS",
        "provider_lifecycle_actions": [
            "provider.memory.restart",
            "provider.prestashop.stop",
        ],
    }
    assert "backup.create" not in result["evidence"]["provider_lifecycle_actions"]
    assert "offhost_backup" not in result["evidence"]
    assert "last_event_hash" not in result["evidence"]
    assert "/srv/private" not in json.dumps(result)


def test_graph_or_audit_problem_is_degraded_not_healthy():
    result = probe_gateway_ready(opener=opener_for(gateway_payload(graph_outcome="FAIL")))
    assert result["ok"] is False
    assert result["state"] == "degraded"
    assert "graph FAIL" in result["text"]


def test_gateway_service_not_running_is_unhealthy():
    payload = gateway_payload()
    payload["operations_broker"]["services"]["mcp_gateway"] = {
        "state": "stopped",
        "health": "unhealthy",
    }
    result = probe_gateway_ready(opener=opener_for(payload))
    assert result["ok"] is False
    assert result["state"] == "unhealthy"


def test_probe_failure_fails_closed_without_exception_details():
    def broken(_request, timeout=0):
        raise ConnectionError("internal endpoint detail")
    result = probe_gateway_ready(opener=broken)
    assert result == {
        "ok": False,
        "state": "unhealthy",
        "text": "Gateway readiness probe failed: ConnectionError",
        "evidence": {},
    }


def test_gateway_ready_url_is_restricted_to_loopback_ready_path():
    assert validate_gateway_ready_url("http://127.0.0.1:8770/ready") == "http://127.0.0.1:8770/ready"
    assert validate_gateway_ready_url("http://localhost:8770/ready") == "http://localhost:8770/ready"
    attempted = False
    def must_not_run(_request, timeout=0):
        nonlocal attempted
        attempted = True
        raise AssertionError("network opener must not run")
    result = probe_gateway_ready("http://example.com:8770/ready", opener=must_not_run)
    assert attempted is False
    assert result["state"] == "unhealthy"
    assert result["text"] == "Gateway readiness probe failed: ValueError"


def test_gateway_evidence_only_attaches_to_gateway_required_provider():
    payload = {"items": [{"id": "prestashop"}, {"id": "memory"}]}
    registry = {
        "prestashop": {"provider_manifest": {"gateway_required": True}},
        "memory": {},
    }
    evidence = {"ok": True, "state": "healthy", "text": "Gateway READY"}
    result = apply_gateway_evidence(payload, registry, evidence)
    assert result["items"][0]["gateway_access"] == evidence
    assert "gateway_access" not in result["items"][1]


def test_four_layer_health_preserves_explicit_gateway_degraded_state():
    payload = {
        "items": [{
            "id": "prestashop",
            "services": [{"active": "active"}],
            "probe": {"live": True, "ready": True, "ready_text": "ready"},
            "source_access": {"ok": True, "text": "source ok"},
            "gateway_access": {
                "ok": False,
                "state": "degraded",
                "text": "Gateway READY · graph FAIL",
            },
        }],
        "summary": {},
    }
    registry = {
        "prestashop": {
            "source_probe": "prestashop",
            "provider_manifest": {
                "gateway_required": True,
                "health_contract": {
                    "process_health": True,
                    "provider_health": True,
                    "source_health": True,
                    "gateway_health": True,
                },
            },
        }
    }
    result = apply_health_layers(payload, registry)
    gateway = result["items"][0]["health_layers"]["gateway"]
    assert gateway["state"] == "degraded"
    assert result["summary"]["health_layers"]["gateway"]["degraded"] == 1
