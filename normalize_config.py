#!/usr/bin/env python3
"""Post-process MTProto DC config: optional secret filter and flag merge."""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import sys
from pathlib import Path
from typing import Any


DC_OPTION_FLAG_SECRET = 1 << 10
FAKE_TLS_PREFIX = 0xEE


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_ip(raw: str) -> str:
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return raw.strip()


def secret_bytes(option: dict[str, Any]) -> bytes | None:
    secret = option.get("secret")
    if not isinstance(secret, str) or not secret:
        return None
    try:
        return base64.b64decode(secret, validate=False)
    except Exception:
        return None


def is_secret_endpoint(option: dict[str, Any]) -> bool:
    if int(option.get("flags", 0)) & DC_OPTION_FLAG_SECRET:
        return True
    raw = secret_bytes(option)
    if raw is None:
        return False
    return True


def is_fake_tls_endpoint(option: dict[str, Any]) -> bool:
    raw = secret_bytes(option)
    return raw is not None and len(raw) > 0 and raw[0] == FAKE_TLS_PREFIX


def filter_secret_endpoints(config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    options = config.get("options")
    if not isinstance(options, list):
        raise ValueError("config.options must be a list")

    kept: list[dict[str, Any]] = []
    dropped = 0
    for raw in options:
        if not isinstance(raw, dict):
            continue
        if is_secret_endpoint(raw) or is_fake_tls_endpoint(raw):
            dropped += 1
            continue
        kept.append(dict(raw))

    cleaned = dict(config)
    cleaned["options"] = kept
    return cleaned, dropped


def normalize_option_ips(config: dict[str, Any]) -> dict[str, Any]:
    """Always canonicalize IPv4/IPv6 address strings."""
    options = config.get("options")
    if not isinstance(options, list):
        raise ValueError("config.options must be a list")

    normalized: list[dict[str, Any]] = []
    for raw in options:
        if not isinstance(raw, dict):
            continue
        option = dict(raw)
        option["ip"] = normalize_ip(str(option.get("ip", "")))
        normalized.append(option)

    cleaned = dict(config)
    cleaned["options"] = normalized
    return cleaned


def merge_options(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged["flags"] = int(existing.get("flags", 0)) | int(incoming.get("flags", 0))
    merged["ip"] = normalize_ip(str(existing.get("ip", "")))

    if "secret" in incoming and "secret" not in merged:
        merged["secret"] = incoming["secret"]
    elif "secret" in incoming and "secret" in merged:
        if int(incoming.get("flags", 0)) & DC_OPTION_FLAG_SECRET:
            merged["secret"] = incoming["secret"]

    if "secret" in merged:
        merged["flags"] = int(merged["flags"]) | DC_OPTION_FLAG_SECRET
    return merged


def merge_flags_config(config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Merge options that share (dc, ip, port) via flags OR. IPs must already be normalized."""
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
    parser.add_argument(
        "--drop-secret",
        choices=("0", "1"),
        help="Override DROP_SECRET_ENDPOINTS (1=drop SECRET/Fake-TLS endpoints)",
    )
    parser.add_argument(
        "--merge-flags",
        choices=("0", "1"),
        help="Override MERGE_FLAGS (1=merge same dc/ip/port with flags OR)",
    )
    args = parser.parse_args()

    # Defaults: keep secrets; merge duplicate endpoints after IP normalize.
    drop_secret = (
        args.drop_secret == "1"
        if args.drop_secret is not None
        else env_flag("DROP_SECRET_ENDPOINTS", False)
    )
    merge_flags = (
        args.merge_flags == "1"
        if args.merge_flags is not None
        else env_flag("MERGE_FLAGS", True)
    )

    path: Path = args.path
    config = json.loads(path.read_text(encoding="utf-8"))
    before = len(config.get("options", []))
    dropped_secret = 0
    removed_dupes = 0

    if drop_secret:
        config, dropped_secret = filter_secret_endpoints(config)

    # IPv6/IPv4 canonicalization always runs.
    config = normalize_option_ips(config)

    if merge_flags:
        config, removed_dupes = merge_flags_config(config)

    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Normalized {path}: {before} -> {len(config.get('options', []))} options"
        f" (drop_secret={int(drop_secret)} dropped={dropped_secret},"
        f" merge_flags={int(merge_flags)} removed={removed_dupes})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
