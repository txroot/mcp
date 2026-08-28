from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse


DEFAULT_GATEWAY_MCP_URL = "http://127.0.0.1:8770/mcp"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_RESPONSE_BYTES = 128 * 1024
_ALLOWED_TOOLS = {
    "gateway_vm_status",
    "gateway_provider_inventory",
    "gateway_prepare_operation",
    "gateway_execute_operation",
}


class GatewayClientError(RuntimeError):
    pass


def validate_gateway_mcp_url(url: str) -> str:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid Gateway MCP port") from exc
    if parsed.scheme != "http":
        raise ValueError("Gateway MCP scheme must be http")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("Gateway MCP host must be loopback")
    if port is None or not 1 <= port <= 65535:
        raise ValueError("Gateway MCP URL must include a valid port")
    if parsed.path != "/mcp" or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Gateway MCP path must be exactly /mcp")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Gateway MCP URL cannot contain credentials")
    return url


def _structured_tool_result(document: dict[str, Any]) -> dict[str, Any]:
    if "error" in document:
        error = document.get("error") or {}
        raise GatewayClientError(str(error.get("message") or "Gateway JSON-RPC error"))
    result = document.get("result")
    if not isinstance(result, dict):
        raise GatewayClientError("Gateway tool result is missing")
    if result.get("isError") is True:
        text = "Gateway tool returned an error"
        content = result.get("content") or []
        if content and isinstance(content[0], dict) and content[0].get("text"):
            text = str(content[0]["text"])
        raise GatewayClientError(text[:500])
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content") or []
    if content and isinstance(content[0], dict) and isinstance(content[0].get("text"), str):
        try:
            parsed = json.loads(content[0]["text"])
        except json.JSONDecodeError as exc:
            raise GatewayClientError("Gateway tool returned non-JSON text") from exc
        if isinstance(parsed, dict):
            return parsed
    raise GatewayClientError("Gateway tool returned no structured object")


def call_gateway_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout: float = 3.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """Call one explicitly allowlisted Sofia Gateway MCP tool over loopback HTTP."""
    if tool_name not in _ALLOWED_TOOLS:
        raise ValueError("Gateway tool is outside the Control Center allowlist")
    validated_url = validate_gateway_mcp_url(url)
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        validated_url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "sofia-control-center/1",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise GatewayClientError("Gateway MCP response exceeds size limit")
        if not 200 <= status < 300:
            raise GatewayClientError(f"Gateway MCP HTTP {status}")
        document = json.loads(raw.decode("utf-8"))
        if not isinstance(document, dict):
            raise GatewayClientError("Gateway MCP response must be an object")
        return _structured_tool_result(document)
    except GatewayClientError:
        raise
    except Exception as exc:
        raise GatewayClientError(f"Gateway MCP call failed: {type(exc).__name__}") from exc
