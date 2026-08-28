from sofia_health import apply_health_layers


def registry_config(*, source_probe: str = "prestashop") -> dict:
    return {
        "provider_manifest": {
            "gateway_required": True,
            "health_contract": {
                "process_health": True,
                "provider_health": True,
                "source_health": True,
                "gateway_health": True,
            },
        },
        "source_probe": source_probe,
    }


def item(**overrides) -> dict:
    base = {
        "id": "prestashop",
        "services": [
            {"active": "active"},
            {"active": "active"},
        ],
        "probe": {
            "live": True,
            "ready": True,
            "live_text": "ok",
            "ready_text": "ready",
        },
        "source_access": {"ok": True, "text": "source ok"},
        "state": "online",
    }
    base.update(overrides)
    return base


def apply(single_item: dict, config: dict | None = None) -> dict:
    payload = {"items": [single_item], "summary": {}}
    registry = {single_item["id"]: config or registry_config()}
    return apply_health_layers(payload, registry)


def test_four_layers_are_materialized_without_overwriting_legacy_state():
    result = apply(item())
    current = result["items"][0]

    assert current["state"] == "online"
    assert current["health_layers"]["process"]["state"] == "healthy"
    assert current["health_layers"]["provider"]["state"] == "healthy"
    assert current["health_layers"]["source"]["state"] == "healthy"
    assert current["health_layers"]["gateway"]["state"] == "unknown"
    assert current["health_layers"]["gateway"]["required"] is True
    assert "pending" in current["health_layers"]["gateway"]["text"].lower()


def test_process_health_distinguishes_partial_and_zero_active_services():
    partial = item(services=[{"active": "active"}, {"active": "inactive"}])
    assert apply(partial)["items"][0]["health_layers"]["process"]["state"] == "degraded"

    offline = item(services=[{"active": "inactive"}, {"active": "failed"}])
    assert apply(offline)["items"][0]["health_layers"]["process"]["state"] == "unhealthy"


def test_provider_health_uses_ready_then_live_evidence():
    degraded = item(probe={"live": True, "ready": False, "ready_text": "warming"})
    assert apply(degraded)["items"][0]["health_layers"]["provider"]["state"] == "degraded"

    unhealthy = item(probe={"live": False, "ready": False, "live_text": "offline"})
    assert apply(unhealthy)["items"][0]["health_layers"]["provider"]["state"] == "unhealthy"


def test_source_health_is_unknown_when_required_evidence_is_missing():
    current = item()
    current.pop("source_access")
    source = apply(current)["items"][0]["health_layers"]["source"]

    assert source["state"] == "unknown"
    assert source["required"] is True


def test_gateway_health_only_becomes_healthy_with_real_evidence():
    current = item(gateway_access={"ok": True, "text": "Gateway READY"})
    gateway = apply(current)["items"][0]["health_layers"]["gateway"]

    assert gateway == {"state": "healthy", "text": "Gateway READY", "required": True}


def test_legacy_provider_still_gets_four_layers_without_claiming_gateway_health():
    current = item()
    current["id"] = "memory"
    current.pop("source_access")
    config = {"services": ["memory.service"]}

    layers = apply(current, config)["items"][0]["health_layers"]

    assert set(layers) == {"process", "provider", "source", "gateway"}
    assert layers["source"]["required"] is False
    assert layers["gateway"]["required"] is False
    assert layers["gateway"]["state"] == "unknown"


def test_manifest_memory_does_not_require_separate_source_probe():
    current = item(
        id="memory",
        gateway_access={"ok": True, "state": "healthy", "text": "Gateway READY"},
    )
    current.pop("source_access")
    config = {
        "source_probe": "",
        "provider_manifest": {
            "gateway_required": True,
            "health_contract": {
                "process_health": True,
                "provider_health": True,
                "source_health": False,
                "gateway_health": True,
            },
        },
    }

    layers = apply(current, config)["items"][0]["health_layers"]

    assert layers["source"] == {
        "state": "unknown",
        "text": "Source health not required by contract",
        "required": False,
    }
    assert layers["gateway"] == {
        "state": "healthy",
        "text": "Gateway READY",
        "required": True,
    }


def test_summary_contains_counts_per_health_layer():
    result = apply(item())
    counts = result["summary"]["health_layers"]

    assert counts["process"]["healthy"] == 1
    assert counts["provider"]["healthy"] == 1
    assert counts["source"]["healthy"] == 1
    assert counts["gateway"]["unknown"] == 1
