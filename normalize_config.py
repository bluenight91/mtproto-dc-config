#!/usr/bin/env python3
"""Normalize addresses and dedupe MTProto DC config options."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from pathlib import Path
from typing import Any


DC_OPTION_FLAG_SECRET = 1 << 10


def normalize_ip(raw: str) -> str:
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return raw.strip()


def merge_options(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged["flags"] = int(existing.get("flags", 0)) | int(incoming.get("flags", 0))
    merged["ip"] = normalize_ip(str(existing.get("ip", "")))

    # Prefer an explicit secret when either side carries one.
    if "secret" in incoming and "secret" not in merged:
        merged["secret"] = incoming["secret"]
    elif "secret" in incoming and "secret" in merged:
        # Keep the secret that belongs with the SECRET flag when possible.
        if int(incoming.get("flags", 0)) & DC_OPTION_FLAG_SECRET:
            merged["secret"] = incoming["secret"]

    if "secret" in merged:
        merged["flags"] = int(merged["flags"]) | DC_OPTION_FLAG_SECRET
    return merged


def dedupe_config(config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    options = config.get("options")
    if not isinstance(options, list):
        raise ValueError("config.options must be a list")

    ordered: list[dict[str, Any]] = []
    index_by_key: dict[tuple[Any, str, Any], int] = {}
    removed = 0

    for raw in options:
        if not isinstance(raw, dict):
            continue
        option = dict(raw)
        option["ip"] = normalize_ip(str(option.get("ip", "")))
        key = (option.get("id"), option["ip"], option.get("port"))
        if key in index_by_key:
            pos = index_by_key[key]
            ordered[pos] = merge_options(ordered[pos], option)
            removed += 1
            continue
        index_by_key[key] = len(ordered)
        ordered.append(option)

    cleaned = dict(config)
    cleaned["options"] = ordered
    return cleaned, removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to mtproto-dc-config.json")
    args = parser.parse_args()

    path: Path = args.path
    config = json.loads(path.read_text(encoding="utf-8"))
    cleaned, removed = dedupe_config(config)
    path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Normalized {path}: {len(config.get('options', []))} -> {len(cleaned['options'])} options"
        f" (removed {removed} duplicates)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
