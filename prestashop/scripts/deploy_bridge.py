#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from ftplib import FTP
from pathlib import Path

HOME = Path.home()
PROJECT = Path(__file__).resolve().parents[1]
BRIDGE = PROJECT / "bridge" / "prestashop_mcp_bridge.php"
FTP_ENV = HOME / ".config" / "mcp-ftp-eletrix" / "runtime.env"
MCP_ENV = HOME / ".config" / "prestashop-mcp" / "runtime.env"
BASE_URL = "https://eletrix.pt/shop/_orders_check"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"\'')
    return out


def update_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    prefix = key + "="
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            out.append(prefix + value)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(prefix + value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)


def main() -> None:
    ap = argparse.ArgumentParser(description="Deploy a versioned Eletrix PrestaShop MCP bridge over FTP.")
    ap.add_argument("--activate", action="store_true", help="Update the local MCP runtime env to the new bridge URL")
    args = ap.parse_args()

    cfg = read_env(FTP_ENV)
    host = cfg["FTP_HOST"]
    user = cfg["FTP_USER"]
    password = cfg["FTP_PASSWORD"]

    data = BRIDGE.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:12]
    remote_name = f"prestashop_mcp_bridge_{digest}.php"

    ftp = FTP(host, timeout=30)
    ftp.login(user, password)
    with BRIDGE.open("rb") as handle:
        ftp.storbinary(f"STOR {remote_name}", handle)
    remote_size = ftp.size(remote_name)
    ftp.quit()

    if remote_size != len(data):
        raise SystemExit(f"Remote size mismatch: local={len(data)} remote={remote_size}")

    url = f"{BASE_URL}/{remote_name}"
    if args.activate:
        update_env(MCP_ENV, "PRESTASHOP_BRIDGE_URL", url)

    print(f"deployed={remote_name}")
    print(f"bytes={remote_size}")
    print(f"url={url}")
    print(f"activated={'yes' if args.activate else 'no'}")


if __name__ == "__main__":
    main()
