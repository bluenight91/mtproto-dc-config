#!/usr/bin/env python3
"""Minimal static file server for Dokploy / Traefik."""

from __future__ import annotations

import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class JsonAwareHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".json": "application/json; charset=utf-8",
    }

    def log_message(self, format: str, *args) -> None:
        # Keep container logs readable without drowning them.
        if self.command == "GET" and args and str(args[1]).startswith("2"):
            return
        super().log_message(format, *args)


def main() -> None:
    data_dir = os.environ.get("DATA_DIR", "/data")
    port = int(os.environ.get("PORT", "8080"))
    handler = partial(JsonAwareHandler, directory=data_dir)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Serving {data_dir} on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
