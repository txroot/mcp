#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
HOST = "127.0.0.1"
PORT = 18100
TOKEN_PATH = HOME / ".config/mcp-control-center/token"
TOKEN = TOKEN_PATH.read_text().strip()

MCP_REGISTRY = {
    "host-tools": {
        "name": "Host Tools",
        "description": "Local shell, files, Git, Docker and system tools",
        "services": ["host-tools-mcp-v2.service", "host-tools-tunnel-v2.service"],
        "profile": "host-tools-v2",
        "mcp": "http://127.0.0.1:8766/mcp",
        "health": "http://127.0.0.1:18082",
        "admin": "http://127.0.0.1:18082/ui",
        "kind": "HTTP + Tunnel",
        "tools_probe": {"type": "http", "python": str(HOME / ".local/share/host-tools/.venv/bin/python"), "url": "http://127.0.0.1:8766/mcp"},
    },
    "google-tasks": {
        "name": "Google Tasks",
        "description": "Personal Google Tasks MCP",
        "services": ["mcp-google-tasks-tunnel.service"],
        "profile": "google-tasks",
        "mcp": "stdio via tunnel-client",
        "health": "http://127.0.0.1:18102",
        "admin": "http://127.0.0.1:18102/ui",
        "kind": "stdio + Tunnel",
        "tools_probe": {"type": "import", "python": "/opt/google-tasks-mcp/.venv/bin/python", "cwd": "/opt/google-tasks-mcp", "module": "server"},
    },
    "memory": {
        "name": "Memory",
        "description": "Persistent semantic memory for ChatGPT",
        "services": ["mcp-memory.service", "mcp-memory-tunnel.service"],
        "profile": "memory",
        "mcp": "http://127.0.0.1:8765/mcp",
        "health": "http://127.0.0.1:18103",
        "admin": "http://127.0.0.1:18103/ui",
        "kind": "HTTP + Tunnel",
        "tools_probe": {"type": "http", "python": str(HOME / "mcp-memory/.venv/bin/python"), "url": "http://127.0.0.1:8765/mcp"},
    },
    "google-analytics": {
        "name": "Google Analytics",
        "description": "Eletrix GA4 read-only MCP",
        "services": ["mcp-google-analytics.service", "mcp-google-analytics-tunnel.service"],
        "profile": "google-analytics",
        "mcp": "http://127.0.0.1:8767/mcp",
        "health": "http://127.0.0.1:18104",
        "admin": "http://127.0.0.1:18104/ui",
        "kind": "HTTP + Tunnel",
        "tunnel_configured": True,
        "tools_probe": {"type": "http", "python": str(HOME / "chatgpt-workspace/google-analytics-mcp/.venv/bin/python"), "url": "http://127.0.0.1:8767/mcp"},
    },
    "prestashop": {
        "name": "PrestaShop",
        "description": "Eletrix operational read-only MCP",
        "services": ["mcp-prestashop.service", "mcp-prestashop-tunnel.service"],
        "profile": "prestashop",
        "mcp": "http://127.0.0.1:8769/mcp",
        "health": "http://127.0.0.1:18105",
        "admin": "http://127.0.0.1:18105/ui",
        "kind": "HTTP + Tunnel",
        "tunnel_configured": True,
        "tools_probe": {"type": "http", "python": str(HOME / "chatgpt-workspace/mcp/prestashop/.venv/bin/python"), "url": "http://127.0.0.1:8769/mcp"},
    },
}

DETECTED = {}

SAFE_UNITS = {u for cfg in MCP_REGISTRY.values() for u in cfg["services"]}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(api[_ -]?key[\"'=:\s]+)([^\s\"']+)"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)(\S+)"),
]


def redact(text: str) -> str:
    out = text
    for i, rx in enumerate(SECRET_PATTERNS):
        if i == 0:
            out = rx.sub("[redacted]", out)
        else:
            out = rx.sub(lambda m: m.group(1) + "[redacted]", out)
    return out


def run(*args: str, timeout: int = 8) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    uid = os.getuid()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)


def systemctl_show(unit: str) -> dict:
    if unit not in SAFE_UNITS:
        return {"unit": unit, "active": "unknown", "sub": "unknown", "enabled": "unknown", "pid": 0, "since": ""}
    cp = run(
        "systemctl", "--user", "show", unit,
        "--property=ActiveState,SubState,UnitFileState,MainPID,ActiveEnterTimestamp",
    )
    props = {}
    for line in cp.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    try:
        pid_num = int(props.get("MainPID", "0") or 0)
    except ValueError:
        pid_num = 0
    return {
        "unit": unit,
        "active": props.get("ActiveState") or "unknown",
        "sub": props.get("SubState") or "unknown",
        "enabled": props.get("UnitFileState") or "unknown",
        "pid": pid_num,
        "since": props.get("ActiveEnterTimestamp", ""),
    }


def http_probe(base: str) -> dict:
    result = {"live": False, "ready": False, "live_text": "offline", "ready_text": "offline"}
    for key, endpoint in (("live", "/healthz"), ("ready", "/readyz")):
        try:
            req = urllib.request.Request(base + endpoint, headers={"User-Agent": "mcp-control-center/1"})
            with urllib.request.urlopen(req, timeout=1.5) as r:
                body = r.read(256).decode("utf-8", "replace").strip()
                ok = 200 <= r.status < 300
                result[key] = ok
                result[key + "_text"] = body or ("ok" if ok else f"HTTP {r.status}")
        except Exception as exc:
            result[key + "_text"] = type(exc).__name__
    return result


def tcp_probe(target: str) -> dict:
    result = {"live": False, "ready": False, "live_text": "offline", "ready_text": "offline"}
    try:
        host, port_text = target.rsplit(":", 1)
        port = int(port_text)
        with socket.create_connection((host, port), timeout=1.5):
            pass
        result.update({"live": True, "ready": True, "live_text": "tcp ok", "ready_text": "MCP local ready"})
    except Exception as exc:
        result["live_text"] = type(exc).__name__
        result["ready_text"] = type(exc).__name__
    return result


_ANALYTICS_CHECK = {"ts": 0.0, "ok": False, "text": "not checked"}

def analytics_data_probe() -> dict:
    now = time.time()
    if now - float(_ANALYTICS_CHECK.get("ts", 0.0)) < 60:
        return dict(_ANALYTICS_CHECK)
    env = os.environ.copy()
    env_file = HOME / ".config/google-analytics-mcp/runtime.env"
    try:
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = os.path.expandvars(os.path.expanduser(v.strip()))
        project = HOME / "chatgpt-workspace/google-analytics-mcp"
        code = (
            "from analytics_client import run_report; "
            "run_report(dimensions=[], metrics=['activeUsers'], start_date='yesterday', "
            "end_date='yesterday', limit=1); print('OK')"
        )
        cp = subprocess.run(
            [str(project / ".venv/bin/python"), "-c", code],
            cwd=str(project), env=env, capture_output=True, text=True, timeout=12,
        )
        if cp.returncode == 0:
            _ANALYTICS_CHECK.update({"ts": now, "ok": True, "text": "GA4 data access OK"})
        else:
            msg = redact((cp.stderr or cp.stdout or "GA4 check failed").strip())
            if "403" in msg or "sufficient permissions" in msg.lower():
                msg = "GA4 403: service account does not have Viewer access to this property"
            else:
                msg = msg.splitlines()[-1] if msg else "GA4 check failed"
            _ANALYTICS_CHECK.update({"ts": now, "ok": False, "text": msg[:300]})
    except Exception as exc:
        _ANALYTICS_CHECK.update({"ts": now, "ok": False, "text": f"GA4 check: {type(exc).__name__}"})
    return dict(_ANALYTICS_CHECK)


_PRESTASHOP_CHECK = {"ts": 0.0, "ok": False, "text": "not checked"}
def prestashop_data_probe() -> dict:
    now = time.time()
    if now - float(_PRESTASHOP_CHECK.get("ts", 0.0)) < 60:
        return dict(_PRESTASHOP_CHECK)
    env = os.environ.copy()
    env_file = HOME / ".config/prestashop-mcp/runtime.env"
    try:
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = os.path.expandvars(os.path.expanduser(v.strip()))
        project = HOME / "chatgpt-workspace/mcp/prestashop"
        code = "from prestashop_client import health_check; health_check(); print('OK')"
        cp = subprocess.run(
            [str(project / ".venv/bin/python"), "-c", code], cwd=str(project), env=env,
            capture_output=True, text=True, timeout=12,
        )
        if cp.returncode == 0:
            _PRESTASHOP_CHECK.update({"ts": now, "ok": True, "text": "PrestaShop bridge OK"})
        else:
            msg = redact((cp.stderr or cp.stdout or "PrestaShop bridge check failed").strip())
            if "HTTP 404" in msg:
                msg = "Bridge not deployed (HTTP 404)"
            else:
                msg = msg.splitlines()[-1] if msg else "PrestaShop bridge check failed"
            _PRESTASHOP_CHECK.update({"ts": now, "ok": False, "text": msg[:300]})
    except Exception as exc:
        _PRESTASHOP_CHECK.update({"ts": now, "ok": False, "text": f"PrestaShop check: {type(exc).__name__}"})
    return dict(_PRESTASHOP_CHECK)


def memory_stats() -> dict | None:
    db = HOME / "mcp-memory/data/memory.db"
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
        count = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        con.close()
        return {"memories": count, "db_mb": round(db.stat().st_size / 1024 / 1024, 2)}
    except Exception:
        return None


_TOOLS_CACHE: dict[str, dict] = {}

_HTTP_TOOLS_PROBE_CODE = r"""
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client(sys.argv[1]) as transport:
        read_stream, write_stream = transport[0], transport[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            print(json.dumps([
                {
                    "name": tool.name,
                    "title": getattr(tool, "title", None),
                    "description": getattr(tool, "description", "") or "",
                }
                for tool in result.tools
            ]))

asyncio.run(main())
"""

_IMPORT_TOOLS_PROBE_CODE = r"""
import importlib, json, sys
module = importlib.import_module(sys.argv[1])
mcp = module.mcp
tools = []
for name, tool in mcp._tool_manager._tools.items():
    tools.append({
        "name": name,
        "title": getattr(tool, "title", None),
        "description": getattr(tool, "description", "") or "",
    })
print(json.dumps(tools))
"""


def mcp_tools(ident: str, max_age: int = 300) -> dict:
    now = time.time()
    cached = _TOOLS_CACHE.get(ident)
    if cached and now - float(cached.get("ts", 0)) < max_age:
        return {k: v for k, v in cached.items() if k != "ts"}
    cfg = MCP_REGISTRY.get(ident)
    if not cfg:
        return {"ok": False, "count": 0, "tools": [], "text": "Unknown MCP"}
    probe = cfg.get("tools_probe")
    if not probe:
        return {"ok": False, "count": 0, "tools": [], "text": "Tool discovery not configured"}
    try:
        if probe.get("type") == "http":
            cmd = [probe["python"], "-c", _HTTP_TOOLS_PROBE_CODE, probe["url"]]
            cwd = None
        elif probe.get("type") == "import":
            cmd = [probe["python"], "-c", _IMPORT_TOOLS_PROBE_CODE, probe["module"]]
            cwd = probe.get("cwd")
        else:
            raise RuntimeError("Unsupported tool probe type")
        cp = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=18)
        if cp.returncode != 0:
            msg = redact((cp.stderr or cp.stdout or "Tool discovery failed").strip())
            raise RuntimeError(msg.splitlines()[-1] if msg else "Tool discovery failed")
        tools = json.loads(cp.stdout)
        tools = sorted(tools, key=lambda item: str(item.get("name", "")))
        result = {"ok": True, "count": len(tools), "tools": tools, "text": f"{len(tools)} tools discovered"}
    except Exception as exc:
        result = {"ok": False, "count": 0, "tools": [], "text": f"Tool discovery: {type(exc).__name__}: {redact(str(exc))[:280]}"}
    _TOOLS_CACHE[ident] = {"ts": now, **result}
    return result


def mcp_info(ident: str) -> dict | None:
    cfg = MCP_REGISTRY.get(ident)
    if not cfg:
        return None
    services = [systemctl_show(unit) for unit in cfg["services"]]
    return {
        "id": ident,
        "name": cfg["name"],
        "description": cfg["description"],
        "kind": cfg.get("kind", ""),
        "mcp": cfg.get("mcp", ""),
        "profile": cfg.get("profile", ""),
        "tunnel_configured": cfg.get("tunnel_configured", cfg.get("profile") not in (None, "", "OpenAI tunnel pending")),
        "services": services,
        "tools": mcp_tools(ident),
    }


def profile_inventory() -> list[str]:
    d = HOME / ".config/tunnel-client"
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def status_payload() -> dict:
    items = []
    managed_profiles = {cfg["profile"] for cfg in MCP_REGISTRY.values() if cfg.get("profile") and cfg.get("profile") != "OpenAI tunnel pending"}
    for ident, cfg in MCP_REGISTRY.items():
        services = [systemctl_show(u) for u in cfg["services"]]
        probe = tcp_probe(cfg["health"]) if cfg.get("probe_type") == "tcp" else http_probe(cfg["health"])
        all_active = all(s["active"] == "active" for s in services)
        all_enabled = all(s["enabled"] in ("enabled", "static") for s in services)
        state = "online" if all_active and probe["ready"] else ("degraded" if all_active or probe["live"] else "offline")
        item = {
            "id": ident,
            **cfg,
            "services": services,
            "state": state,
            "all_active": all_active,
            "all_enabled": all_enabled,
            "probe": probe,
        }
        if ident == "memory":
            item["memory_stats"] = memory_stats()
        if ident == "google-analytics":
            item["analytics_access"] = analytics_data_probe()
            if not item["analytics_access"].get("ok") or not cfg.get("tunnel_configured", False):
                item["state"] = "degraded" if all_active else "offline"
        if ident == "prestashop":
            item["source_access"] = prestashop_data_probe()
            if not item["source_access"].get("ok") or not cfg.get("tunnel_configured", False):
                item["state"] = "degraded" if all_active else "offline"
        items.append(item)
    detected = []
    for ident, cfg in DETECTED.items():
        if cfg["path"].exists():
            detected.append({"id": ident, "name": cfg["name"], "description": cfg["description"], "path": str(cfg["path"])})
    profiles = profile_inventory()
    unmanaged = [p for p in profiles if p not in managed_profiles]
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "items": items,
        "detected": detected,
        "profiles": profiles,
        "unmanaged_profiles": unmanaged,
        "summary": {
            "online": sum(i["state"] == "online" for i in items),
            "degraded": sum(i["state"] == "degraded" for i in items),
            "offline": sum(i["state"] == "offline" for i in items),
            "managed": len(items),
        },
    }


def service_action(ident: str, action: str) -> tuple[bool, str]:
    if ident not in MCP_REGISTRY or action not in {"start", "stop", "restart"}:
        return False, "Invalid MCP or action"
    units = list(MCP_REGISTRY[ident]["services"])
    if action == "stop":
        units.reverse()
    outputs = []
    ok = True
    for unit in units:
        if unit not in SAFE_UNITS:
            ok = False
            outputs.append(f"{unit}: blocked")
            continue
        cp = run("systemctl", "--user", action, unit, timeout=20)
        if cp.returncode != 0:
            ok = False
        msg = (cp.stderr or cp.stdout or "ok").strip()
        outputs.append(f"{unit}: {msg}")
    return ok, redact("\n".join(outputs))


def logs_for(ident: str, lines: int = 120) -> str:
    if ident not in MCP_REGISTRY:
        return "Unknown MCP"
    lines = max(20, min(lines, 500))
    chunks = []
    for unit in MCP_REGISTRY[ident]["services"]:
        if unit not in SAFE_UNITS:
            continue
        cp = run("journalctl", "--user", "-u", unit, "-n", str(lines), "--no-pager", "--output=short-iso", timeout=10)
        chunks.append(f"===== {unit} =====\n{cp.stdout or cp.stderr}")
    return redact("\n".join(chunks))[-120000:]


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCP Control Center</title>
<style>
:root{color-scheme:dark;--bg:#080d15;--panel:#0f1724;--line:#243247;--soft:#1a2637;--text:#f3f6fb;--muted:#8e9db2;--green:#67d58a;--amber:#f0b84d;--red:#ff6f7d;--blue:#5f8fff;--shadow:0 16px 45px rgba(0,0,0,.22)}
*{box-sizing:border-box}html,body{min-height:100%}body{margin:0;background:radial-gradient(circle at 15% -15%,#14233a 0,transparent 34%),linear-gradient(180deg,#0a101a,#080d15 58%,#070b12);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--text)}
.shell{max-width:1500px;margin:auto;padding:0 28px 44px}.brandbar{height:48px;display:flex;align-items:center;border-bottom:1px solid var(--soft)}.brand{display:flex;align-items:center;gap:9px;font-size:10px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#7da8ff}.brandmark{width:19px;height:19px;border:2px solid var(--blue);border-radius:50%;display:grid;place-items:center;box-shadow:0 0 18px rgba(95,143,255,.2)}.brandmark:after{content:"";width:5px;height:5px;border-radius:50%;background:var(--blue)}.brandsep{color:#56667d}.brandsoft{color:#7e8fa6}
.header{height:72px;display:flex;align-items:center;justify-content:space-between;gap:18px;border-bottom:1px solid var(--soft)}.title{font-size:28px;line-height:1;letter-spacing:-.035em;font-weight:740;margin:0}.toolbar{display:flex;align-items:center;gap:9px}.auto{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px;white-space:nowrap}.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 0 3px rgba(103,213,138,.07)}.divider{width:1px;height:27px;background:var(--line)}.iconbtn{width:37px;height:37px;padding:0;display:grid;place-items:center;border:1px solid var(--line);border-radius:10px;background:rgba(17,25,38,.78);color:#dce6f3;cursor:pointer;transition:.14s}.iconbtn:hover{border-color:#41536e;background:#152034;transform:translateY(-1px)}.iconbtn svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.iconbtn.spinning svg{animation:spin .55s linear}@keyframes spin{to{transform:rotate(360deg)}}
.helpwrap{position:relative}.helpbox{position:absolute;right:0;top:44px;width:min(360px,calc(100vw - 40px));padding:14px 15px;border:1px solid #31415a;border-radius:12px;background:#101826;box-shadow:0 22px 65px rgba(0,0,0,.42);display:none;z-index:30}.helpbox.show{display:block}.helpbox h3{font-size:13px;margin:0 0 7px}.helpbox p{font-size:12px;color:var(--muted);margin:0 0 8px}.helpbox p:last-child{margin-bottom:0}.helpbox code{color:#c5d5e9}
.summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:18px 0 15px}.metric{position:relative;overflow:hidden;min-height:88px;background:linear-gradient(150deg,rgba(17,27,42,.92),rgba(11,18,29,.92));border:1px solid var(--line);border-radius:14px;padding:14px 17px;box-shadow:var(--shadow)}.metric:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:#66758b}.metric.online:before{background:var(--green)}.metric.degraded:before{background:var(--amber)}.metric.profiles:before{background:var(--blue)}.metric b{display:block;font-size:27px;line-height:1;font-weight:760;letter-spacing:-.04em;margin-bottom:8px}.metric span{color:var(--muted);font-size:12px}.pulse{position:absolute;right:17px;bottom:16px;width:25px;height:16px;opacity:.2}.pulse svg{width:100%;height:100%;fill:none;stroke:#8aa0bf;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{background:linear-gradient(155deg,rgba(18,29,45,.97),rgba(11,18,29,.98));border:1px solid var(--line);border-radius:16px;padding:17px;box-shadow:var(--shadow);min-height:260px;display:flex;flex-direction:column}.cardhead{display:flex;justify-content:space-between;gap:12px}.name{font-size:18px;font-weight:750;letter-spacing:-.016em}.desc{color:var(--muted);font-size:12px;margin-top:2px}.pill{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.075em;border-radius:999px;padding:5px 8px;height:max-content;border:1px solid}.pill.online{color:var(--green);background:rgba(103,213,138,.07);border-color:rgba(103,213,138,.28)}.pill.degraded{color:var(--amber);background:rgba(240,184,77,.07);border-color:rgba(240,184,77,.3)}.pill.offline{color:var(--red);background:rgba(255,111,125,.07);border-color:rgba(255,111,125,.3)}
.meta{margin:16px 0 14px;display:grid;gap:8px}.row{display:grid;grid-template-columns:88px minmax(0,1fr);gap:10px;align-items:start}.key{color:#6f829c;font-size:10px;text-transform:uppercase;letter-spacing:.075em}.val{font-size:12px;word-break:break-word;color:#dce5f1}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;background:var(--red)}.dot.on{background:var(--green)}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#c4d2e5;font-size:11px}.actions{margin-top:auto;display:flex;gap:7px;flex-wrap:wrap}.btn{border:1px solid var(--line);background:#131d2b;color:#dfe8f4;border-radius:9px;padding:7px 10px;font-weight:650;font-size:12px;cursor:pointer;transition:.14s}.btn:hover{transform:translateY(-1px);border-color:#40516b;background:#182436}.btn.danger{color:#ff9da6}.link{color:#9cbcff;text-decoration:none}
.section{margin-top:20px}.section.empty{display:none}.section h2{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:#8293a9;margin:0 0 8px}.detected{display:flex;gap:10px;flex-wrap:wrap}.ghost{border:1px dashed #344057;background:rgba(14,20,30,.55);border-radius:12px;padding:11px 13px;min-width:260px}.ghost b{display:block}.ghost span{color:var(--muted);font-size:12px}.profiletag{display:inline-block;margin:3px 4px 0 0;background:#101926;border:1px solid var(--soft);border-radius:999px;padding:4px 8px;font-size:10px;color:#8192a9}
.modal{position:fixed;inset:0;background:rgba(2,5,9,.76);display:none;align-items:center;justify-content:center;padding:24px;z-index:40}.modal.show{display:flex}.modalbox{width:min(1100px,96vw);height:min(760px,90vh);background:#0b111a;border:1px solid #334158;border-radius:16px;box-shadow:0 30px 100px #000;padding:16px;display:flex;flex-direction:column}.modalhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}.logs{background:#070b11;border:1px solid #202c3d;border-radius:10px;padding:14px;white-space:pre-wrap;overflow:auto;flex:1;color:#bcd0ea;font:11px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.notice{position:fixed;right:22px;bottom:22px;max-width:420px;background:#111a27;border:1px solid #33425b;border-radius:11px;padding:10px 12px;display:none;box-shadow:var(--shadow);font-size:12px}.notice.show{display:block}.notice.bad{border-color:#6b3039;color:#ffadb4}
@media(max-width:980px){.summary{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.header{height:68px}.title{font-size:25px}}@media(max-width:620px){.shell{padding:0 15px 32px}.brandbar{height:42px}.brand{font-size:9px;letter-spacing:.11em}.header{height:61px}.title{font-size:22px}.auto span:first-child{display:none}.summary{padding-top:13px}.metric{min-height:80px}.row{grid-template-columns:76px minmax(0,1fr)}}
</style>
</head>
<body><div class="shell">
<div class="brandbar"><div class="brand"><span class="brandmark" aria-hidden="true"></span><span>Microlumin</span><span class="brandsep">·</span><span class="brandsoft">Local Infrastructure</span></div></div>
<div class="header"><h1 class="title">MCP Control Center</h1><div class="toolbar"><div class="auto" title="Status refreshes automatically every 5 seconds"><span>Auto-refresh</span><span class="live-dot"></span><strong>5s</strong></div><span class="divider"></span><button id="refreshBtn" class="iconbtn" type="button" onclick="refresh(true)" title="Refresh now" aria-label="Refresh now"><svg viewBox="0 0 24 24"><path d="M20 11a8.1 8.1 0 0 0-15.5-2M4 4v5h5"></path><path d="M4 13a8.1 8.1 0 0 0 15.5 2M20 20v-5h-5"></path></svg></button><span class="divider"></span><div class="helpwrap"><button class="iconbtn" type="button" onclick="toggleHelp(event)" title="Help" aria-label="Help"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"></circle><path d="M9.8 9a2.35 2.35 0 0 1 4.55.75c0 1.75-2.35 2.05-2.35 3.8"></path><path d="M12 17h.01"></path></svg></button><div id="helpBox" class="helpbox"><h3>About this dashboard</h3><p>Monitors local MCP servers and OpenAI Secure Tunnels on this workstation. Status refreshes every 5 seconds.</p><p>Service actions are restricted to registered units. The dashboard listens only on <code>127.0.0.1</code>.</p><p><strong>Online</strong> means registered services are running and ready. <strong>Degraded</strong> means the MCP is reachable but a dependency or tunnel still needs attention.</p><p>Stopping or restarting Host Tools temporarily interrupts remote access from ChatGPT.</p></div></div></div></div>
<div class="summary"><div class="metric online"><b id="mOnline">—</b><span>Online</span><i class="pulse"><svg viewBox="0 0 28 18"><path d="M1 10h5l3-8 5 15 4-9 3 2h6"></path></svg></i></div><div class="metric degraded"><b id="mDegraded">—</b><span>Degraded</span><i class="pulse"><svg viewBox="0 0 28 18"><path d="M1 10h5l3-8 5 15 4-9 3 2h6"></path></svg></i></div><div class="metric offline"><b id="mOffline">—</b><span>Offline</span><i class="pulse"><svg viewBox="0 0 28 18"><path d="M1 10h5l3-8 5 15 4-9 3 2h6"></path></svg></i></div><div class="metric profiles"><b id="mProfiles">—</b><span>Tunnel profiles</span><i class="pulse"><svg viewBox="0 0 28 18"><path d="M1 10h5l3-8 5 15 4-9 3 2h6"></path></svg></i></div></div>
<div id="grid" class="grid"></div>
<div id="detectedSection" class="section"><h2>Detected but unmanaged</h2><div class="detected" id="detected"></div></div>
<div class="section"><h2>Tunnel profiles</h2><div id="profiles"></div></div>
</div>
<div class="modal" id="modal" onclick="if(event.target===this)closeModal()"><div class="modalbox"><div class="modalhead"><b id="modalTitle">Logs</b><button class="btn" onclick="closeModal()">Close</button></div><pre class="logs" id="logs">Loading…</pre></div></div>
<div class="notice" id="notice"></div>
<script>
const TOKEN=__TOKEN__;
let refreshInFlight=false;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notify(msg,bad=false){const n=document.getElementById('notice');n.textContent=msg;n.className='notice show'+(bad?' bad':'');setTimeout(()=>n.className='notice',4200)}
function toggleHelp(ev){ev.stopPropagation();document.getElementById('helpBox').classList.toggle('show')}
document.addEventListener('click',()=>document.getElementById('helpBox')?.classList.remove('show'));
function serviceLine(s){const on=s.active==='active';return `<div><span class="dot ${on?'on':''}"></span><code>${esc(s.unit)}</code> · ${esc(s.active)}/${esc(s.sub)}${s.pid?` · PID ${s.pid}`:''}</div>`}
function card(i){const ms=i.memory_stats?`<div class="row"><div class="key">Database</div><div class="val">${i.memory_stats.memories} memories · ${i.memory_stats.db_mb} MB</div></div>`:'';const ga=i.analytics_access?`<div class="row"><div class="key">GA4 data</div><div class="val"><span class="dot ${i.analytics_access.ok?'on':''}"></span>${esc(i.analytics_access.text)}</div></div><div class="row"><div class="key">Tunnel</div><div class="val"><span class="dot ${i.tunnel_configured?'on':''}"></span>${i.tunnel_configured?'OpenAI connected':'OpenAI tunnel pending'}</div></div>`:'';const source=i.source_access?`<div class="row"><div class="key">Source</div><div class="val"><span class="dot ${i.source_access.ok?'on':''}"></span>${esc(i.source_access.text)}</div></div><div class="row"><div class="key">Tunnel</div><div class="val"><span class="dot ${i.tunnel_configured?'on':''}"></span>${i.tunnel_configured?'OpenAI connected':'OpenAI tunnel pending'}</div></div>`:'';const admin=i.admin?`<a class="btn link" href="/admin?id=${encodeURIComponent(i.id)}">Admin UI</a>`:'';return `<div class="card"><div class="cardhead"><div><div class="name">${esc(i.name)}</div><div class="desc">${esc(i.description)}</div></div><span class="pill ${i.state}">${i.state}</span></div><div class="meta"><div class="row"><div class="key">Services</div><div class="val">${i.services.map(serviceLine).join('')}</div></div><div class="row"><div class="key">Ready</div><div class="val"><span class="dot ${i.probe.ready?'on':''}"></span>${esc(i.probe.ready_text)}</div></div><div class="row"><div class="key">Profile</div><div class="val"><code>${esc(i.profile)}</code></div></div><div class="row"><div class="key">MCP</div><div class="val"><code>${esc(i.mcp)}</code></div></div>${ga}${source}${ms}</div><div class="actions"><button class="btn" onclick="act('${i.id}','start')">Start</button><button class="btn" onclick="act('${i.id}','restart')">Restart</button><button class="btn danger" onclick="act('${i.id}','stop')">Stop</button><button class="btn" onclick="info('${i.id}','${esc(i.name)}')">Info</button><button class="btn" onclick="logs('${i.id}','${esc(i.name)}')">Logs</button>${admin}</div></div>`}
async function refresh(manual=false){if(refreshInFlight)return;refreshInFlight=true;const b=document.getElementById('refreshBtn');if(manual)b?.classList.add('spinning');try{const r=await fetch('/api/status',{cache:'no-store'});const d=await r.json();document.getElementById('mOnline').textContent=d.summary.online;document.getElementById('mDegraded').textContent=d.summary.degraded;document.getElementById('mOffline').textContent=d.summary.offline;document.getElementById('mProfiles').textContent=d.profiles.length;document.getElementById('grid').innerHTML=d.items.map(card).join('');const ds=document.getElementById('detectedSection');document.getElementById('detected').innerHTML=d.detected.map(x=>`<div class="ghost"><b>${esc(x.name)}</b><span>${esc(x.description)}</span><br><code>${esc(x.path)}</code></div>`).join('');ds.classList.toggle('empty',!d.detected.length);document.getElementById('profiles').innerHTML=d.profiles.map(x=>`<span class="profiletag">${esc(x)}</span>`).join('')+(d.unmanaged_profiles.length?`<div class="desc" style="margin-top:8px">Unmanaged: ${d.unmanaged_profiles.map(esc).join(', ')}</div>`:'');}catch(e){notify('Status refresh failed: '+e,true)}finally{refreshInFlight=false;if(manual)setTimeout(()=>b?.classList.remove('spinning'),180)}}
async function act(id,action){if(action==='stop'&&!confirm('Stop '+id+'?'))return;notify(`${action} ${id}…`);try{const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-MCP-Control-Token':TOKEN},body:JSON.stringify({id,action})});const d=await r.json();notify(d.message||`${action} completed`,!d.ok);setTimeout(()=>refresh(false),900)}catch(e){notify('Action failed: '+e,true)}}
async function info(id,name){document.getElementById('modal').classList.add('show');document.getElementById('modalTitle').textContent='Info · '+name;const box=document.getElementById('logs');box.textContent='Discovering MCP tools…';try{const r=await fetch('/api/info?id='+encodeURIComponent(id),{headers:{'X-MCP-Control-Token':TOKEN},cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.error||'Info request failed');const lines=[];lines.push(d.description||'');lines.push('');lines.push('Transport: '+(d.kind||'—'));lines.push('MCP: '+(d.mcp||'—'));lines.push('Tunnel profile: '+(d.profile||'—'));lines.push('Tunnel: '+(d.tunnel_configured?'configured':'pending / not required'));lines.push('');lines.push('System services ('+(d.services||[]).length+'):');for(const s of (d.services||[]))lines.push('  • '+s.unit+' — '+s.active+'/'+s.sub+' · '+s.enabled);lines.push('');const t=d.tools||{};lines.push('MCP tools ('+(t.count||0)+')'+(t.ok?'':' — discovery unavailable'));if(!t.ok&&t.text)lines.push('  '+t.text);for(const tool of (t.tools||[])){const title=tool.title&&tool.title!==tool.name?' — '+tool.title:'';lines.push('');lines.push('  '+tool.name+title);if(tool.description)lines.push('    '+tool.description.replace(/\s+/g,' ').trim())}box.textContent=lines.join('\n')}catch(e){box.textContent='Info failed: '+e}}
async function logs(id,name){document.getElementById('modal').classList.add('show');document.getElementById('modalTitle').textContent='Logs · '+name;document.getElementById('logs').textContent='Loading…';try{const r=await fetch('/api/logs?id='+encodeURIComponent(id),{headers:{'X-MCP-Control-Token':TOKEN},cache:'no-store'});const d=await r.json();document.getElementById('logs').textContent=d.logs||d.error||'No logs'}catch(e){document.getElementById('logs').textContent=String(e)}}
function closeModal(){document.getElementById('modal').classList.remove('show')}
refresh(false);setInterval(()=>refresh(false),5000);
</script></body></html>'''.replace('__TOKEN__', json.dumps(TOKEN))


def admin_shell(ident: str):
    cfg = MCP_REGISTRY.get(ident)
    if not cfg or not cfg.get("admin"):
        return None
    name = html.escape(cfg["name"])
    admin_url = html.escape(cfg["admin"], quote=True)
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{name} - MCP Control Center</title><style>html,body{{height:100%;margin:0;background:#080d15;color:#f3f6fb;font:14px system-ui}}body{{display:flex;flex-direction:column}}.bar{{height:52px;flex:0 0 52px;display:flex;align-items:center;gap:14px;padding:0 18px;border-bottom:1px solid #243247;background:#0f1724}}.back{{color:#cfe0ff;text-decoration:none;border:1px solid #33445d;background:#131d2b;border-radius:9px;padding:7px 10px;font-weight:650}}.back:hover{{background:#182436}}.title{{font-weight:750}}iframe{{border:0;width:100%;flex:1;background:white}}</style></head><body><div class="bar"><a class="back" href="/">&#8592; MCP Control Center</a><div class="title">{name} · Admin UI</div></div><iframe src="{admin_url}" title="{name} Admin UI"></iframe></body></html>""".format(name=name, admin_url=admin_url)


class Handler(BaseHTTPRequestHandler):
    server_version = "MCPControlCenter/1.0"
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        return secrets.compare_digest(self.headers.get("X-MCP-Control-Token", ""), TOKEN)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/admin":
            ident = parse_qs(p.query).get("id", [""])[0]
            page = admin_shell(ident)
            if page is None:
                self.send_error(404, "Unknown MCP Admin UI"); return
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; frame-src http://127.0.0.1:*; frame-ancestors 'none'")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers(); self.wfile.write(body); return
        if p.path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers(); self.wfile.write(body); return
        if p.path == "/api/status":
            self._json(status_payload()); return
        if p.path == "/api/info":
            if not self._authorized(): self._json({"error":"unauthorized"},403); return
            ident = parse_qs(p.query).get("id", [""])[0]
            info = mcp_info(ident)
            if info is None: self._json({"error":"unknown MCP"},404); return
            self._json(info); return
        if p.path == "/api/logs":
            if not self._authorized(): self._json({"error":"unauthorized"},403); return
            ident = parse_qs(p.query).get("id", [""])[0]
            self._json({"id": ident, "logs": logs_for(ident)}); return
        if p.path == "/healthz":
            self._json({"status":"ok"}); return
        self._json({"error":"not found"},404)

    def do_POST(self):
        if self.path != "/api/action": self._json({"error":"not found"},404); return
        if not self._authorized(): self._json({"ok":False,"message":"unauthorized"},403); return
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 4096)
            data = json.loads(self.rfile.read(n) or b"{}")
            ok, msg = service_action(str(data.get("id","")), str(data.get("action","")))
            self._json({"ok":ok,"message":msg or ("Concluído" if ok else "Falhou")},200 if ok else 500)
        except Exception as exc:
            self._json({"ok":False,"message":redact(str(exc))},500)


if __name__ == "__main__":
    print(f"MCP Control Center listening on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
