import json

import pytest

from sofia_gateway_client import (
    GatewayClientError,
    call_gateway_tool,
    validate_gateway_mcp_url,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.body[:size]


def test_gateway_mcp_url_is_loopback_only():
    assert validate_gateway_mcp_url("http://127.0.0.1:8770/mcp") == "http://127.0.0.1:8770/mcp"
    with pytest.raises(ValueError, match="loopback"):
        validate_gateway_mcp_url("http://example.com:8770/mcp")
    with pytest.raises(ValueError, match="exactly /mcp"):
        validate_gateway_mcp_url("http://127.0.0.1:8770/other")


def test_call_tool_uses_tools_call_and_structured_content():
    captured = {}

    def opener(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "{}"}],
                "isError": False,
                "structuredContent": {"allowed_actions": ["provider.memory.restart"]},
            },
        })

    result = call_gateway_tool(
        "http://127.0.0.1:8770/mcp",
        "gateway_vm_status",
        {},
        opener=opener,
    )

    assert result == {"allowed_actions": ["provider.memory.restart"]}
    assert captured["url"] == "http://127.0.0.1:8770/mcp"
    assert captured["body"]["method"] == "tools/call"
    assert captured["body"]["params"] == {"name": "gateway_vm_status", "arguments": {}}
    assert captured["timeout"] == 3.0


def test_non_allowlisted_gateway_tool_is_rejected_before_network():
    with pytest.raises(ValueError, match="outside"):
        call_gateway_tool("http://127.0.0.1:8770/mcp", "shell_exec", {})


def test_gateway_tool_error_is_fail_closed():
    def opener(_request, timeout=0):
        return FakeResponse({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "PermissionError: blocked"}],
                "isError": True,
            },
        })

    with pytest.raises(GatewayClientError, match="blocked"):
        call_gateway_tool(
            "http://127.0.0.1:8770/mcp",
            "gateway_prepare_operation",
            {"action": "provider.memory.restart"},
            opener=opener,
        )
