from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from .provider_inventory_resolvers import canonical_status_tools


DEFAULT_STATUS_GATEWAY_URL = "http://127.0.0.1:8770/mcp"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_RESPONSE_BYTES = 128 * 1024
_ALLOWED_STATUS_TOOLS = frozenset(canonical_status_tools().values())


class ProviderStatusClientError(RuntimeError):
    pass


def allowed_status_tools() -> tuple[str, ...]:
    return tuple(sorted(_ALLOWED_STATUS_TOOLS))


def validate_status_gateway_url(url: str) -> str:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid status Gateway port") from exc
    if parsed.scheme != "http":
        raise ValueError("status Gateway scheme must be http")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("status Gateway host must be loopback")
    if port is None or not 1 <= port <= 65535:
        raise ValueError("status Gateway URL must include a valid port")
    if parsed.path != "/mcp" or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("status Gateway path must be exactly /mcp")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("status Gateway URL cannot contain credentials")
    return url


def _structured_result(document: dict[str, Any]) -> dict[str, Any]:
    if "error" in document:
        raise ProviderStatusClientError("status Gateway returned JSON-RPC error")
    result = document.get("result")
    if not isinstance(result, dict):
        raise ProviderStatusClientError("status Gateway tool result is missing")
    if result.get("isError") is True:
        raise ProviderStatusClientError("status Gateway tool returned an error")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content") or []
    if content and isinstance(content[0], dict) and isinstance(content[0].get("text"), str):
        try:
            parsed = json.loads(content[0]["text"])
        except json.JSONDecodeError as exc:
            raise ProviderStatusClientError("status Gateway returned non-JSON text") from exc
        if isinstance(parsed, dict):
            return parsed
    raise ProviderStatusClientError("status Gateway returned no structured object")


class ProviderStatusClient:
    """Strict read-only client used by the canary inventory aggregator."""

    def __init__(
        self,
        url: str = DEFAULT_STATUS_GATEWAY_URL,
        *,
        timeout: float = 3.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.url = validate_status_gateway_url(url)
        self.timeout = float(timeout)
        self.opener = opener

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in _ALLOWED_STATUS_TOOLS:
            raise ValueError("provider status tool is outside the canary allowlist")
        if arguments:
            raise ValueError("provider status tools must be called without arguments")
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": {}},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "User-Agent": "sofia-provider-inventory-canary/1",
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = int(getattr(response, "status", 200))
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ProviderStatusClientError("status Gateway response exceeds size limit")
            if not 200 <= status < 300:
                raise ProviderStatusClientError(f"status Gateway HTTP {status}")
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict):
                raise ProviderStatusClientError("status Gateway response must be an object")
            return _structured_result(document)
        except ProviderStatusClientError:
            raise
        except Exception as exc:
            raise ProviderStatusClientError(
                f"status Gateway call failed: {type(exc).__name__}"
            ) from exc
