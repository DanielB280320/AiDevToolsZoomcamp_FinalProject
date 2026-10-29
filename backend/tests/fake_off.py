"""A fake Open Food Facts server on a loopback port (spec F6.4: no real network in tests).

It speaks the two endpoints the app uses (`/cgi/search.pl`, `/api/v2/product/<code>.json`), records
every request, and can be switched into failure modes: `5xx`, `slow` (answers after `delay`
seconds), `garbage` (not JSON) or `wrong_shape` (JSON without `products`).
"""

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest


def product(code: str, name: str, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "code": code,
        "product_name": name,
        "brands": "Example Dairy, Other Brand",
        "nutriments": {
            "energy-kcal_100g": 73,
            "proteins_100g": 9.5,
            "carbohydrates_100g": 3.6,
            "fat_100g": 2,
        },
        "allergens_tags": ["en:milk"],
        "ingredients_analysis_tags": ["en:non-vegan", "en:vegetarian"],
    }
    value.update(overrides)
    return value


@dataclass
class Recorded:
    path: str
    query: dict[str, list[str]]
    user_agent: str | None


@dataclass
class FakeOff:
    base_url: str
    products: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "ok"
    delay: float = 0.0
    requests: list[Recorded] = field(default_factory=list)

    def searches(self) -> list[Recorded]:
        return [r for r in self.requests if r.path == "/cgi/search.pl"]

    def lookups(self) -> list[Recorded]:
        return [r for r in self.requests if r.path.startswith("/api/v2/product/")]


def _handler(state: FakeOff) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            state.requests.append(
                Recorded(url.path, parse_qs(url.query), self.headers.get("User-Agent"))
            )
            if state.mode == "slow":
                time.sleep(state.delay)
            if state.mode == "5xx":
                self._send(503, b'{"error": "down"}')
            elif state.mode == "garbage":
                self._send(200, b"<html>not json</html>", "text/html")
            elif state.mode == "wrong_shape":
                self._send(200, b'{"unexpected": true}')
            elif url.path == "/cgi/search.pl":
                terms = parse_qs(url.query).get("search_terms", [""])[0].lower()
                found = [
                    p for p in state.products if terms in str(p.get("product_name", "")).lower()
                ]
                self._send(200, json.dumps({"products": found}).encode())
            elif url.path.startswith("/api/v2/product/"):
                code = url.path.rsplit("/", 1)[1].removesuffix(".json")
                match = next((p for p in state.products if p["code"] == code), None)
                if match is None:
                    self._send(404, b'{"status": 0, "status_verbose": "product not found"}')
                else:
                    self._send(200, json.dumps({"status": 1, "product": match}).encode())
            else:
                self._send(404, b"{}")

    return Handler


@pytest.fixture
def fake_off() -> Iterator[FakeOff]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(FakeOff("")))
    # Rebuild the handler around the real state once the port is known.
    state = FakeOff(f"http://127.0.0.1:{server.server_address[1]}")
    server.RequestHandlerClass = _handler(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
