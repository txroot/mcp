from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from sofia_gateway_client import call_gateway_tool


_ALLOWED_ACTIONS = {"start", "stop", "restart"}
_APPROVAL_RE = re.compile(r"pvap_[a-f0-9]{32}")


def apply_lifecycle_availability(
    payload: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    gateway_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Expose lifecycle buttons only when both manifest and live Gateway allow them."""
    evidence = gateway_evidence.get("evidence") or {}
    allowed = set(evidence.get("provider_lifecycle_actions") or [])
    for item in payload.get("items", []):
        provider_id = str(item.get("id") or "")
        config = registry.get(provider_id, {})
        manifest = config.get("provider_manifest") or {}
        mapping = config.get("lifecycle_actions") or {}
        mediated = manifest.get("gateway_required") is True and bool(mapping)
        item["lifecycle"] = {
            "mode": "gateway" if mediated else "unavailable",
            "legacy_direct": False,
            "start": mediated and mapping.get("start") in allowed,
            "stop": mediated and mapping.get("stop") in allowed,
            "restart": mediated and mapping.get("restart") in allowed,
        }
    return payload


@dataclass(frozen=True)
class PendingLifecycle:
    approval_id: str
    provider_id: str
    action: str
    gateway_action: str
    expires_monotonic: float


class LifecycleController:
    """Two-phase provider lifecycle controller backed only by Sofia OS Gateway tools."""

    def __init__(
        self,
        registry: dict[str, dict[str, Any]],
        gateway_url: str,
        *,
        call_tool: Callable[[str, str, dict[str, Any]], dict[str, Any]] = call_gateway_tool,
        now: Callable[[], float] = time.monotonic,
        local_ttl_seconds: float = 600.0,
    ) -> None:
        self.registry = registry
        self.gateway_url = gateway_url
        self.call_tool = call_tool
        self.now = now
        self.local_ttl_seconds = local_ttl_seconds
        self._pending: dict[str, PendingLifecycle] = {}
        self._lock = threading.Lock()

    def _gateway_action(self, provider_id: str, action: str) -> str:
        if action not in _ALLOWED_ACTIONS:
            raise ValueError("Unsupported lifecycle action")
        config = self.registry.get(provider_id)
        if not isinstance(config, dict):
            raise ValueError("Unknown provider")
        manifest = config.get("provider_manifest") or {}
        if manifest.get("gateway_required") is not True:
            raise PermissionError("Provider lifecycle is not Gateway-managed")
        mapping = config.get("lifecycle_actions") or {}
        gateway_action = str(mapping.get(action) or "")
        if not gateway_action:
            raise PermissionError("Provider lifecycle is not declared by manifest")
        expected = f"provider.{provider_id}.{action}"
        if gateway_action != expected:
            raise PermissionError("Provider lifecycle action does not match provider identity")
        return gateway_action

    def availability(self, provider_id: str) -> dict[str, bool]:
        status = self.call_tool(self.gateway_url, "gateway_vm_status", {})
        allowed = set(status.get("allowed_actions") or [])
        result: dict[str, bool] = {}
        for action in sorted(_ALLOWED_ACTIONS):
            try:
                gateway_action = self._gateway_action(provider_id, action)
            except (ValueError, PermissionError):
                result[action] = False
                continue
            result[action] = gateway_action in allowed
        return result

    def prepare(self, provider_id: str, action: str) -> dict[str, Any]:
        gateway_action = self._gateway_action(provider_id, action)
        status = self.call_tool(self.gateway_url, "gateway_vm_status", {})
        allowed = set(status.get("allowed_actions") or [])
        if gateway_action not in allowed:
            return {
                "ok": False,
                "phase": "blocked",
                "code": "gateway_action_unavailable",
                "provider_id": provider_id,
                "action": action,
                "gateway_action": gateway_action,
                "message": "Gateway does not currently advertise this provider lifecycle action.",
            }
        prepared = self.call_tool(
            self.gateway_url,
            "gateway_prepare_operation",
            {"action": gateway_action},
        )
        approval_id = str(prepared.get("approval_id") or "")
        if not _APPROVAL_RE.fullmatch(approval_id):
            raise RuntimeError("Gateway returned an invalid approval id")
        if prepared.get("effect_applied") is not False:
            raise RuntimeError("Gateway prepare unexpectedly reported an applied effect")
        if str(prepared.get("confirmation_required") or "") != "CONFIRMO":
            raise RuntimeError("Gateway returned an unexpected confirmation contract")
        pending = PendingLifecycle(
            approval_id=approval_id,
            provider_id=provider_id,
            action=action,
            gateway_action=gateway_action,
            expires_monotonic=self.now() + self.local_ttl_seconds,
        )
        with self._lock:
            self._pending[approval_id] = pending
        return {
            "ok": True,
            "phase": "prepared",
            "provider_id": provider_id,
            "action": action,
            "gateway_action": gateway_action,
            "approval_id": approval_id,
            "expires_at": prepared.get("expires_at"),
            "confirmation_required": "CONFIRMO",
            "effect_applied": False,
            "message": str(prepared.get("description") or "Lifecycle action prepared by Gateway."),
        }

    def execute(self, approval_id: str, confirmation: str) -> dict[str, Any]:
        if not _APPROVAL_RE.fullmatch(approval_id):
            raise ValueError("Invalid lifecycle approval id")
        if confirmation != "CONFIRMO":
            raise PermissionError("Explicit CONFIRMO is required")
        with self._lock:
            pending = self._pending.get(approval_id)
        if pending is None:
            raise PermissionError("Lifecycle approval was not prepared by this Control Center instance")
        if self.now() > pending.expires_monotonic:
            with self._lock:
                self._pending.pop(approval_id, None)
            raise PermissionError("Lifecycle approval expired locally; prepare again")
        executed = self.call_tool(
            self.gateway_url,
            "gateway_execute_operation",
            {"approval_id": approval_id, "confirmation": confirmation},
        )
        if executed.get("outcome") != "PASS" or executed.get("effect_applied") is not True:
            raise RuntimeError("Gateway lifecycle execution did not return PASS")
        if str(executed.get("action") or "") != pending.gateway_action:
            raise RuntimeError("Gateway executed an unexpected lifecycle action")
        with self._lock:
            self._pending.pop(approval_id, None)
        return {
            "ok": True,
            "phase": "executed",
            "provider_id": pending.provider_id,
            "action": pending.action,
            "gateway_action": pending.gateway_action,
            "approval_id": approval_id,
            "effect_applied": True,
            "outcome": "PASS",
            "message": f"{pending.action} completed through Sofia OS Gateway.",
        }
