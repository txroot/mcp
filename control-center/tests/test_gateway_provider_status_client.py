import json

import pytest

from gateway.provider_status_client import (
    ProviderStatusClient,
    ProviderStatusClientError,
    allowed_status_tools,
    validate_status_gateway_url,
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


def test_status_gateway_url_is_loopback_only():
    assert validate_status_gateway_url("http://127.0.0.1:8770/mcp") == "http://127.0.0.1:8770/mcp"
    with pytest.raises(ValueError, match="loopback"):
        validate_status_gateway_url("http://example.com:8770/mcp")
    with pytest.raises(ValueError, match="exactly /mcp"):
        validate_status_gateway_url("http://127.0.0.1:8770/ready")


def test_allowed_status_tools_are_read_only_contracts_only():
    tools = set(allowed_status_tools())
    assert "gateway_health" in tools
    assert "mail.send.status" in tools
    assert "prestashop.category_writer.status" in tools
    assert "gateway_prepare_operation" not in tools
    assert "gateway_execute_operation" not in tools
    assert "shell_exec" not in tools


def test_client_calls_static_status_tool_without_arguments():
    captured = {}

    def opener(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": False,
                    "structuredContent": {"status": "READY", "credential_ref": "must-not-be-forwarded-by-inventory"},
                },
            }
        )

    client = ProviderStatusClient(opener=opener)
    result = client.call("mail.read.status", {})

    assert result["status"] == "READY"
    assert captured["url"] == "http://127.0.0.1:8770/mcp"
    assert captured["body"]["method"] == "tools/call"
    assert captured["body"]["params"] == {"name": "mail.read.status", "arguments": {}}
    assert captured["timeout"] == 3.0


def test_client_rejects_non_status_tool_and_arguments_before_network():
    client = ProviderStatusClient(opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network")))
    with pytest.raises(ValueError, match="outside"):
        client.call("gateway_prepare_operation", {})
    with pytest.raises(ValueError, match="without arguments"):
        client.call("mail.read.status", {"unexpected": True})


def test_client_fails_closed_without_exposing_remote_error_text():
    def opener(_request, timeout=0):
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "secret remote stack trace"}],
                },
            }
        )

    client = ProviderStatusClient(opener=opener)
    with pytest.raises(ProviderStatusClientError, match="returned an error") as exc:
        client.call("mail.read.status", {})
    assert "secret remote stack trace" not in str(exc.value)
