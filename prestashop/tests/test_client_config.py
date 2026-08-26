import os

import pytest

from prestashop_client import get_settings


def test_requires_https(monkeypatch):
    monkeypatch.setenv("PRESTASHOP_BRIDGE_URL", "http://example.test/bridge.php")
    monkeypatch.setenv("PRESTASHOP_BRIDGE_TOKEN", "x")
    with pytest.raises(RuntimeError, match="HTTPS"):
        get_settings()


def test_reads_numeric_defaults(monkeypatch):
    monkeypatch.setenv("PRESTASHOP_BRIDGE_URL", "https://example.test/bridge.php")
    monkeypatch.setenv("PRESTASHOP_BRIDGE_TOKEN", "x")
    monkeypatch.delenv("PRESTASHOP_DEFAULT_LANG_ID", raising=False)
    monkeypatch.delenv("PRESTASHOP_DEFAULT_SHOP_ID", raising=False)
    cfg = get_settings()
    assert cfg.lang_id == 2
    assert cfg.shop_id == 1
