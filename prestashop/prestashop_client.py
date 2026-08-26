from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Settings:
    bridge_url: str
    token: str
    expected_db_user: str
    lang_id: int
    shop_id: int


def get_settings() -> Settings:
    bridge_url = os.environ.get("PRESTASHOP_BRIDGE_URL", "").strip()
    token = os.environ.get("PRESTASHOP_BRIDGE_TOKEN", "").strip()
    expected = os.environ.get("PRESTASHOP_EXPECTED_DB_USER", "").strip()
    if not bridge_url or not token:
        raise RuntimeError("PRESTASHOP_BRIDGE_URL and PRESTASHOP_BRIDGE_TOKEN are required")
    if not bridge_url.lower().startswith("https://"):
        raise RuntimeError("PRESTASHOP_BRIDGE_URL must use HTTPS")
    try:
        lang_id = int(os.environ.get("PRESTASHOP_DEFAULT_LANG_ID", "2"))
        shop_id = int(os.environ.get("PRESTASHOP_DEFAULT_SHOP_ID", "1"))
    except ValueError as exc:
        raise RuntimeError("PRESTASHOP_DEFAULT_LANG_ID and PRESTASHOP_DEFAULT_SHOP_ID must be integers") from exc
    return Settings(bridge_url, token, expected, lang_id, shop_id)


def request_bridge(mode: str, *, timeout: int = 45, **params: Any) -> dict[str, Any]:
    cfg = get_settings()
    query = {"mode": mode, "lang_id": cfg.lang_id, "shop_id": cfg.shop_id}
    query.update({k: v for k, v in params.items() if v is not None})
    url = cfg.bridge_url + ("&" if "?" in cfg.bridge_url else "?") + urllib.parse.urlencode(query)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {cfg.token}",
            "Accept": "application/json",
            "User-Agent": "microlumin-prestashop-mcp/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"PrestaShop bridge HTTP {exc.code}: {body[:1500]}") from exc
    except Exception as exc:
        raise RuntimeError(f"PrestaShop bridge request failed: {type(exc).__name__}: {exc}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"PrestaShop bridge returned invalid JSON: {body[:1000]}") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError(f"PrestaShop bridge returned an error: {payload}")
    return payload


def health_check() -> dict[str, Any]:
    cfg = get_settings()
    payload = request_bridge("health")
    user = str(payload.get("server", {}).get("authenticated_db_user", ""))
    actual = user.split("@", 1)[0]
    if cfg.expected_db_user and actual != cfg.expected_db_user:
        raise RuntimeError(f"Unexpected database user {actual!r}")
    security = payload.get("security", {})
    if security.get("arbitrary_sql_supported") is not False or security.get("write_queries_supported") is not False:
        raise RuntimeError("Bridge did not confirm fixed-query read-only mode")
    return payload
