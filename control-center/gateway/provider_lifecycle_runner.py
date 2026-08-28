#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pwd
import subprocess
from typing import Any


TARGET_USER = "eletrix"
PROVIDERS: dict[str, tuple[str, ...]] = {
    "prestashop": ("mcp-prestashop.service", "mcp-prestashop-tunnel.service"),
    "google-analytics": ("mcp-google-analytics.service", "mcp-google-analytics-tunnel.service"),
    "memory": ("mcp-memory.service", "mcp-memory-tunnel.service"),
}
ACTIONS = {"start", "stop", "restart"}


def _user_env() -> dict[str, str]:
    account = pwd.getpwnam(TARGET_USER)
    runtime = f"/run/user/{account.pw_uid}"
    return {
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
    }


def _systemctl_command(*args: str) -> list[str]:
    env = _user_env()
    return [
        "runuser",
        "-u",
        TARGET_USER,
        "--",
        "env",
        f"XDG_RUNTIME_DIR={env['XDG_RUNTIME_DIR']}",
        f"DBUS_SESSION_BUS_ADDRESS={env['DBUS_SESSION_BUS_ADDRESS']}",
        "systemctl",
        "--user",
        *args,
    ]


def _run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env={"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin")},
    )


def unit_state(unit: str) -> str:
    result = _run(_systemctl_command("is-active", unit), timeout=10)
    state = (result.stdout or result.stderr).strip().splitlines()
    return state[-1] if state else "unknown"


def _postflight_ok(action: str, state: str) -> bool:
    if action in {"start", "restart"}:
        return state == "active"
    return state in {"inactive", "failed"}


def execute(provider: str, action: str) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ValueError("provider outside lifecycle allowlist")
    if action not in ACTIONS:
        raise ValueError("action outside lifecycle allowlist")

    declared_units = list(PROVIDERS[provider])
    before = {unit: unit_state(unit) for unit in declared_units}
    units = list(reversed(declared_units)) if action == "stop" else declared_units
    commands: list[dict[str, Any]] = []

    for unit in units:
        result = _run(_systemctl_command(action, unit), timeout=30)
        commands.append({
            "unit": unit,
            "returncode": result.returncode,
            "stderr": (result.stderr or "")[-300:].strip(),
        })
        if result.returncode != 0:
            raise RuntimeError(f"{provider} {action} failed for {unit}")

    after = {unit: unit_state(unit) for unit in declared_units}
    bad = {unit: state for unit, state in after.items() if not _postflight_ok(action, state)}
    if bad:
        raise RuntimeError(f"postflight failed: {bad}")

    return {
        "provider": provider,
        "action": action,
        "units": declared_units,
        "before": before,
        "after": after,
        "postflight": "PASS",
        "commands": commands,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Allowlisted Sofia provider lifecycle runner")
    parser.add_argument("provider", choices=sorted(PROVIDERS))
    parser.add_argument("action", choices=sorted(ACTIONS))
    args = parser.parse_args()
    result = execute(args.provider, args.action)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
