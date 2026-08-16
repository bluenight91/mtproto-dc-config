#!/usr/bin/env python3
"""Fetch extra Telegram backup sources and merge into mtproto-dc-config.json.

The official generator only pulls apv3.stel.com via Google DoH. SukkaW-style
mirrors also union Firebase + App Engine channels, which can expose additional
STATIC/SECRET endpoints (and occasionally other seeds).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DC_OPTION_FLAG_IPV6 = 1 << 0
DC_OPTION_FLAG_MEDIA_ONLY = 1 << 1
DC_OPTION_FLAG_TCPO_ONLY = 1 << 2
DC_OPTION_FLAG_CDN = 1 << 3
DC_OPTION_FLAG_STATIC = 1 << 4
DC_OPTION_FLAG_SECRET = 1 << 10
FUNCTIONAL_FLAGS = DC_OPTION_FLAG_MEDIA_ONLY | DC_OPTION_FLAG_TCPO_ONLY | DC_OPTION_FLAG_CDN

BACKUP_RSA_PEM = b"""-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEAyr+18Rex2ohtVy8sroGPBwXD3DOoKCSpjDqYoXgCqB7ioln4eDCF
fOBUlfXUEvM/fnKCpF46VkAftlb4VuPDeQSS/ZxZYEGqHaywlroVnXHIjgqoxiAd
192xRGreuXIaUKmkwlM9JID9WS2jUsTpzQ91L8MEPLJ/4zrBwZua8W5fECwCCh2c
9G5IzzBm+otMS/YKwmR1olzRCyEkyAEjXWqBI9Ftv5eG8m0VkBzOG655WIYdyV0H
fDK/NWcvGqa0w/nriMD6mDjKOryamw0OP9QuYgMN0C9xMW9y8SmP4h92OAWodTYg
Y1hZCxdv6cs5UnW9+PWvS+WIbkh+GaWYxwIDAQAB
-----END RSA PUBLIC KEY-----
"""

TIMEOUT_SEC = 20


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "mtproto-dc-config/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC, context=ssl.create_default_context()) as resp:
        return resp.read()


def clean_base64(text: str) -> str:
    filtered = "".join(
        ch for ch in text if ch.isalnum() or ch in {"+", "/", "="}
    )
    while len(filtered) % 4 != 0:
        filtered += "="
    return filtered


class TlReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def remaining(self) -> int:
        return max(0, len(self.data) - self.offset)

    def read_data(self, length: int) -> bytes:
        if length > self.remaining():
            raise ValueError("TL buffer underrun")
        start = self.offset
        self.offset += length
        return self.data[start : self.offset]

    def read_i32(self) -> int:
        return struct.unpack("<i", self.read_data(4))[0]

    def read_tl_bytes(self) -> bytes:
        first = self.read_data(1)[0]
        if first < 254:
            length = first
            prefix = 1
        elif first == 254:
            length_bytes = self.read_data(3)
            length = length_bytes[0] | (length_bytes[1] << 8) | (length_bytes[2] << 16)
            prefix = 4
        else:
            raise ValueError("invalid TL bytes prefix")
        result = self.read_data(length)
        padding = (4 - ((prefix + length) % 4)) % 4
        if padding:
            self.read_data(padding)
        return result

    def read_tl_string(self) -> str:
        return self.read_tl_bytes().decode("utf-8")


def rsa_public_modpow(blob: bytes) -> bytes:
    key = serialization.load_pem_public_key(BACKUP_RSA_PEM)
    if not isinstance(key, rsa.RSAPublicKey):
        raise TypeError("backup key is not RSA")
    numbers = key.public_numbers()
    value = int.from_bytes(blob[:256], "big")
    return pow(value, numbers.e, numbers.n).to_bytes(256, "big")


def aes_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def ipv4_string(value: int) -> str:
    value &= 0xFFFFFFFF
    return f"{(value >> 24) & 0xFF}.{(value >> 16) & 0xFF}.{(value >> 8) & 0xFF}.{value & 0xFF}"


def read_backup_endpoint(reader: TlReader, dc_id: int, constructor: int | None = None) -> dict[str, Any]:
    constructor = 0xD433AD73 if constructor is None else constructor
    if constructor not in {0xD433AD73, 0x37982646}:
        raise ValueError(f"unsupported endpoint constructor 0x{constructor:08x}")
    ip_i = reader.read_i32() & 0xFFFFFFFF
    port = reader.read_i32()
    if not (1 <= dc_id <= 5 and 1 <= port <= 65535):
        raise ValueError("invalid backup endpoint")
    secret = None
    if constructor == 0x37982646:
        secret = reader.read_tl_bytes()
    return {
        "dc_id": dc_id,
        "ip": ipv4_string(ip_i),
        "port": port,
        "secret": secret,
    }


def parse_backup_config(data: bytes) -> list[dict[str, Any]]:
    reader = TlReader(data)
    constructor = reader.read_i32() & 0xFFFFFFFF
    timestamp = reader.read_i32()
    expiration = reader.read_i32()
    now = int(time.time())
    if timestamp >= now + 20 * 60 or expiration <= now - 20 * 60:
        raise ValueError(
            f"backup outside validity ({timestamp}...{expiration}, now {now})"
        )

    endpoints: list[dict[str, Any]] = []
    if constructor == 0xD997C3C5:
        dc_id = reader.read_i32()
        if reader.read_i32() & 0xFFFFFFFF != 0x1CB5C415:
            raise ValueError("invalid legacy vector")
        count = reader.read_i32()
        if not (1 <= count <= 1024):
            raise ValueError("invalid legacy count")
        for _ in range(count):
            endpoints.append(read_backup_endpoint(reader, dc_id, None))
    elif constructor == 0x5A592A6C:
        rule_count = reader.read_i32()
        if not (1 <= rule_count <= 1024):
            raise ValueError("invalid rule count")
        for _ in range(rule_count):
            if reader.read_i32() & 0xFFFFFFFF != 0x4679B65F:
                raise ValueError("invalid access point rule")
            reader.read_tl_string()  # phone prefix rules (union all)
            dc_id = reader.read_i32()
            endpoint_count = reader.read_i32()
            if not (1 <= endpoint_count <= 1024):
                raise ValueError("invalid rule endpoint count")
            for _ in range(endpoint_count):
                endpoint_constructor = reader.read_i32() & 0xFFFFFFFF
                endpoints.append(
                    read_backup_endpoint(reader, dc_id, endpoint_constructor)
                )
    else:
        raise ValueError(f"unsupported backup constructor 0x{constructor:08x}")
    return endpoints


def decode_backup_blob(blob: bytes) -> list[dict[str, Any]]:
    if len(blob) < 256:
        raise ValueError("backup blob too short")
    block = rsa_public_modpow(blob[:256])
    decrypted = aes_cbc_decrypt(block[32:], block[:32], block[16:32])
    if len(decrypted) != 224:
        raise ValueError("invalid AES payload length")
    digest = hashlib.sha256(decrypted[:208]).digest()[:16]
    if digest != decrypted[208:224]:
        raise ValueError("backup hash mismatch")
    data_length = struct.unpack("<I", decrypted[:4])[0]
    if data_length == 0 or data_length > 204 or data_length % 4 != 0:
        raise ValueError("invalid TL length")
    return parse_backup_config(decrypted[4 : 4 + data_length])


def fetch_doh_apv3() -> list[dict[str, Any]]:
    payload = json.loads(http_get("https://dns.google.com/resolve?name=apv3.stel.com&type=16"))
    answers = payload.get("Answer") or []
    parts = []
    for answer in answers:
        data = answer.get("data")
        if isinstance(data, str):
            parts.append(clean_base64(data).rstrip("="))
    if not parts:
        raise ValueError("DoH TXT empty")
    parts.sort(key=len, reverse=True)
    encoded = clean_base64("".join(parts))
    return decode_backup_blob(base64.b64decode(encoded))


def fetch_firebase_rtdb() -> list[dict[str, Any]]:
    raw = http_get("https://reserve-5a846.firebaseio.com/ipconfigv3.json").decode("utf-8")
    text = json.loads(raw)
    if not isinstance(text, str):
        raise ValueError("firebase payload not string")
    return decode_backup_blob(base64.b64decode(clean_base64(text)))


def fetch_firestore() -> list[dict[str, Any]]:
    payload = json.loads(
        http_get(
            "https://firestore.googleapis.com/v1/projects/reserve-5a846/databases/(default)/documents/ipconfig/v3"
        )
    )
    text = payload["fields"]["data"]["stringValue"]
    return decode_backup_blob(base64.b64decode(clean_base64(text)))


def fetch_appengine() -> list[dict[str, Any]]:
    text = http_get("https://dns-telegram.appspot.com").decode("utf-8").strip()
    return decode_backup_blob(base64.b64decode(clean_base64(text)))


SOURCES = (
    ("doh-apv3", fetch_doh_apv3),
    ("firebase-rtdb", fetch_firebase_rtdb),
    ("firestore", fetch_firestore),
    ("appengine", fetch_appengine),
)


def endpoint_flags(ip: str, has_secret: bool) -> int:
    flags = DC_OPTION_FLAG_STATIC
    if ":" in ip:
        flags |= DC_OPTION_FLAG_IPV6
    if has_secret:
        flags |= DC_OPTION_FLAG_SECRET
    return flags


def merge_endpoint(config: dict[str, Any], endpoint: dict[str, Any]) -> bool:
    options = config.setdefault("options", [])
    secret_b64 = (
        base64.b64encode(endpoint["secret"]).decode("ascii")
        if endpoint.get("secret") is not None
        else None
    )
    matched = False
    for option in options:
        if (
            option.get("id") != endpoint["dc_id"]
            or option.get("ip") != endpoint["ip"]
            or option.get("port") != endpoint["port"]
        ):
            continue
        existing_flags = int(option.get("flags", 0))
        if existing_flags & FUNCTIONAL_FLAGS:
            continue
        if option.get("secret") != secret_b64:
            continue
        option["flags"] = existing_flags | endpoint_flags(
            endpoint["ip"], secret_b64 is not None
        )
        matched = True
    if matched:
        return False

    option: dict[str, Any] = {
        "id": endpoint["dc_id"],
        "ip": endpoint["ip"],
        "port": endpoint["port"],
        "flags": endpoint_flags(endpoint["ip"], secret_b64 is not None),
    }
    if secret_b64 is not None:
        option["secret"] = secret_b64
    options.append(option)
    return True


def collect_endpoints() -> tuple[list[dict[str, Any]], list[str]]:
    seen: set[tuple[Any, ...]] = set()
    collected: list[dict[str, Any]] = []
    notes: list[str] = []
    for name, fetcher in SOURCES:
        try:
            endpoints = fetcher()
            added = 0
            for endpoint in endpoints:
                key = (
                    endpoint["dc_id"],
                    endpoint["ip"],
                    endpoint["port"],
                    base64.b64encode(endpoint["secret"]).decode("ascii")
                    if endpoint.get("secret") is not None
                    else None,
                )
                if key in seen:
                    continue
                seen.add(key)
                collected.append(endpoint)
                added += 1
            notes.append(f"{name}: ok (+{added}, raw {len(endpoints)})")
        except Exception as error:  # noqa: BLE001 - best-effort sources
            notes.append(f"{name}: failed ({error})")
    return collected, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Path to mtproto-dc-config.json")
    parser.add_argument(
        "--enable",
        choices=("0", "1"),
        help="Override EXTRA_BACKUP_SOURCES",
    )
    args = parser.parse_args()

    enabled = (
        args.enable == "1"
        if args.enable is not None
        else env_flag("EXTRA_BACKUP_SOURCES", True)
    )
    if not enabled:
        print("EXTRA_BACKUP_SOURCES disabled; skipping", file=sys.stderr)
        return 0

    path: Path = args.path
    config = json.loads(path.read_text(encoding="utf-8"))
    before = len(config.get("options", []))
    endpoints, notes = collect_endpoints()
    added = 0
    for endpoint in endpoints:
        if merge_endpoint(config, endpoint):
            added += 1
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for note in notes:
        print(f"extra-backup {note}", file=sys.stderr)
    print(
        f"Merged extra backups into {path}: {before} -> {len(config.get('options', []))} "
        f"(unique endpoints {len(endpoints)}, newly added {added})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
