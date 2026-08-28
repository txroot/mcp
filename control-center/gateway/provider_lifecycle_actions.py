from __future__ import annotations

from pathlib import Path
from typing import Any


PROVIDERS = ("prestashop", "google-analytics", "memory")
ACTIONS = ("start", "stop", "restart")


def build_provider_lifecycle_actions(
    *,
    runner: str | Path = "/usr/local/lib/pedrovault/pedrovault-provider-lifecycle-runner",
    interlock: str | Path = "/usr/local/lib/pedrovault/pedrovault-runtime-interlock",
) -> dict[str, dict[str, Any]]:
    """Return static ALLOWED_ACTIONS entries for the PedroVault operations broker.

    These entries are a candidate Gateway integration artifact. They intentionally
    encode provider and lifecycle action in the broker allowlist itself so the
    prepare_operation API remains parameter-free beyond its existing action string.
    """
    runner_path = str(runner)
    interlock_path = str(interlock)
    result: dict[str, dict[str, Any]] = {}
    for provider in PROVIDERS:
        for action in ACTIONS:
            gateway_action = f"provider.{provider}.{action}"
            result[gateway_action] = {
                "description": f"{action.capitalize()} allowlisted provider {provider} through governed lifecycle runner.",
                "commands": [[
                    interlock_path,
                    "run",
                    "--owner",
                    f"broker:{gateway_action}",
                    "--",
                    runner_path,
                    provider,
                    action,
                ]],
                "timeout": 120,
            }
    return result
