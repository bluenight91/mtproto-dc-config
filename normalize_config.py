#!/usr/bin/env python3
"""Normalize addresses and dedupe MTProto DC config options."""

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
    return secret_bytes(option) is not None


def is_fake_tls_endpoint(option: dict[str, Any]) -> bool:
    raw = secret_bytes(option)
    return raw is not None and len(raw) > 0 and raw[0] == FAKE_TLS_PREFIX


def should_drop_option(option: dict[str, Any], *, drop_secret: bool, drop_fake_tls: bool) -> bool:
    if drop_secret and is_secret_endpoint(option):
        return True
    if drop_fake_tls and is_fake_tls_endpoint(option):
        return True
    return False


def merge_options(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged["flags"] = int(existing.get("flags", 0)) | int(incoming.get("flags", 0))
    merged["ip"] = normalize_ip(str(existing.get("ip", "")))
    # Secrets are filtered separately; never re-introduce them during dedupe.
    merged.pop("secret", None)
    merged["flags"] = int(merged["flags"]) & ~DC_OPTION_FLAG_SECRET
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


def filter_options(
    config: dict[str, Any], *, drop_secret: bool, drop_fake_tls: bool
) -> tuple[dict[str, Any], int]:
    options = config.get("options")
    if not isinstance(options, list):
        raise ValueError("config.options must be a list")

    kept: list[dict[str, Any]] = []
    dropped = 0
    for raw in options:
        if not isinstance(raw, dict):
            continue
        if should_drop_option(raw, drop_secret=drop_secret, drop_fake_tls=drop_fake_tls):
            dropped += 1
            continue
        kept.append(raw)

    cleaned = dict(config)
    cleaned["options"] = kept
    return cleaned, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to mtproto-dc-config.json")
    parser.add_argument(
        "--keep-secret",
        action="store_true",
        help="Keep SECRET / Fake-TLS endpoints (default: drop them)",
    )
    args = parser.parse_args()

    # Default: drop all secret endpoints so proxy split rules are not poisoned
    # by Fake-TLS IPs (Google SNI, non-Telegram-looking addresses, multi-port probes).
    drop_secret = not args.keep_secret and env_flag("DROP_SECRET_ENDPOINTS", True)
    drop_fake_tls = env_flag("DROP_FAKE_TLS_ENDPOINTS", True)

    path: Path = args.path
    config = json.loads(path.read_text(encoding="utf-8"))
    before = len(config.get("options", []))

    filtered, dropped_secret = filter_options(
        config, drop_secret=drop_secret, drop_fake_tls=drop_fake_tls and not drop_secret
    )
    # If drop_secret already removed all secrets, fake-tls filter is redundant.
    cleaned, removed_dupes = dedupe_config(filtered)

    path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Normalized {path}: {before} -> {len(cleaned['options'])} options"
        f" (dropped {dropped_secret} secret/fake-TLS, removed {removed_dupes} duplicates)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
