import prestashop_client as client


def _payload(grants):
    return {
        "ok": True,
        "server": {"authenticated_db_user": "prestashop_readonly@localhost"},
        "security": {"arbitrary_sql_supported": False, "write_queries_supported": False},
        "tables": {},
        "grants": grants,
    }


def _env(monkeypatch):
    monkeypatch.setenv("PRESTASHOP_BRIDGE_URL", "https://example.test/bridge.php")
    monkeypatch.setenv("PRESTASHOP_BRIDGE_TOKEN", "x")
    monkeypatch.setenv("PRESTASHOP_EXPECTED_DB_USER", "prestashop_readonly")


def test_health_accepts_select_only(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(client, "request_bridge", lambda mode: _payload([
        "GRANT USAGE ON *.* TO `prestashop_readonly`@`localhost`",
        "GRANT SELECT ON `prestashop`.* TO `prestashop_readonly`@`localhost`",
    ]))
    assert client.health_check()["ok"] is True


def test_health_rejects_write_grant(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(client, "request_bridge", lambda mode: _payload([
        "GRANT SELECT, INSERT ON `prestashop`.* TO `prestashop_readonly`@`localhost`",
    ]))
    try:
        client.health_check()
    except RuntimeError as exc:
        assert "non-read-only privilege: INSERT" in str(exc)
    else:
        raise AssertionError("write grant was not rejected")
