#!/usr/bin/env python3
"""Serve only mtproto-dc-config.json for Dokploy / Traefik."""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


class ConfigHandler(BaseHTTPRequestHandler):
    output_file: Path

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in {"/", "/mtproto-dc-config.json"}:
            self._send_json()
            return
        self.send_error(404, "Not Found")

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in {"/", "/mtproto-dc-config.json"}:
            self._send_json(body=False)
            return
        self.send_error(404, "Not Found")

    def _send_json(self, body: bool = True) -> None:
        try:
            data = self.output_file.read_bytes()
        except OSError:
            self.send_error(503, "Config not ready")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if body:
            self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        if self.command in {"GET", "HEAD"} and args and str(args[1]).startswith("2"):
            return
        super().log_message(format, *args)


def main() -> None:
    output_file = Path(
        os.environ.get(
            "OUTPUT_FILE",
            os.path.join(os.environ.get("DATA_DIR", "/data"), "mtproto-dc-config.json"),
        )
    )
    port = int(os.environ.get("PORT", "8080"))

    class BoundHandler(ConfigHandler):
        pass

    BoundHandler.output_file = output_file
    server = ThreadingHTTPServer(("0.0.0.0", port), BoundHandler)
    print(f"Serving {output_file} on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
