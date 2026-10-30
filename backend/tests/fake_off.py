"""pytest fixture for the fake Open Food Facts server (the server itself: tests/off_server.py)."""

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from tests.off_server import FakeOff, Recorded, _handler, product

__all__ = ["FakeOff", "Recorded", "fake_off", "product"]


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
