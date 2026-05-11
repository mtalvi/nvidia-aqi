#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Merge upstream DNS servers into Docker's daemon.json (host-side, run with sudo).

OpenShell sandboxes often cannot reach Docker's loopback resolver (127.0.0.11).
Pointing Docker at public or corporate resolvers lets the embedded DNS forward
correctly so containers can resolve external hostnames.

Usage:
  sudo python3 deploy/openshell/scripts/configure_docker_dns.py --dry-run
  sudo python3 deploy/openshell/scripts/configure_docker_dns.py --apply --restart

Environment:
  OPENSHELL_DOCKER_DNS  Comma-separated IPs (default: 1.1.1.1,8.8.8.8)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _default_dns() -> list[str]:
    raw = os.environ.get("OPENSHELL_DOCKER_DNS", "1.1.1.1,8.8.8.8")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _merge_dns(cfg: dict, dns: list[str]) -> dict:
    out = dict(cfg)
    existing = list(out.get("dns") or [])
    merged: list[str] = []
    for x in existing + dns:
        if x not in merged:
            merged.append(x)
    out["dns"] = merged
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--daemon-json",
        type=Path,
        default=Path("/etc/docker/daemon.json"),
        help="Path to Docker daemon.json",
    )
    parser.add_argument(
        "--dns",
        default=",".join(_default_dns()),
        help="Comma-separated DNS server IPs to ensure are present",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write daemon.json (requires root)",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Run systemctl restart docker after --apply (requires root)",
    )
    args = parser.parse_args()
    dns = [x.strip() for x in args.dns.split(",") if x.strip()]
    if not dns:
        print("No DNS servers given.", file=sys.stderr)
        return 2

    path: Path = args.daemon_json
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                print(f"{path}: root must be a JSON object", file=sys.stderr)
                return 1
        except json.JSONDecodeError as e:
            print(f"{path}: invalid JSON: {e}", file=sys.stderr)
            return 1
    else:
        cfg = {}

    merged = _merge_dns(cfg, dns)
    print(f"Effective dns list: {merged['dns']}")

    if merged == cfg:
        print("daemon.json already contains those DNS entries; nothing to merge.")
        if args.restart and args.apply:
            print("(Skipping restart; no file change.)")
        return 0

    print("\nProposed daemon.json snippet (dns key only):")
    print(json.dumps({"dns": merged["dns"]}, indent=2))

    if not args.apply:
        print("\nDry-run only. Re-run with --apply (and optionally --restart) as root to write the file.")
        return 0

    if os.geteuid() != 0:
        print("error: --apply requires root (use sudo).", file=sys.stderr)
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(f".json.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
    if path.exists():
        shutil.copy2(path, backup)
        print(f"Backed up existing file to {backup}")

    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")

    if args.restart:
        try:
            subprocess.run(["systemctl", "restart", "docker"], check=True)
            print("Ran: systemctl restart docker")
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"warning: could not restart docker via systemctl: {e}", file=sys.stderr)
            print("Restart Docker manually, then recreate your OpenShell sandbox.")
            return 1

    print("\nNext: recreate the sandbox, then verify from inside it:")
    print("  openshell sandbox exec -n <name> -- python3 -c \"import socket; print(socket.gethostbyname('integrate.api.nvidia.com'))\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
