"""QA (#220): the sign-in rate limit behind CloudFront is per client account, not per edge.

Behind CloudFront many viewers share an edge address, and nginx hands the backend one client
address (ADR 0012). The F1.6 limit is keyed by the e-mail hash (D49), so:

* two clients arriving from the SAME address (one CloudFront edge) are counted separately, and
* one e-mail stays locked whatever address the attempts come from (rotating edges or a spoofed
  `X-Forwarded-For` cannot reset it).

Each `TestClient` gets its own ASGI `client` address, which is what the backend would see after
nginx and uvicorn's `--proxy-headers`.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.integration.auth_helpers import PASSWORD, Api, problem

EDGE = ("130.176.0.10", 443)  # one CloudFront edge, shared by both viewers
OTHER_EDGE = ("64.252.0.20", 443)
WRONG = "wrong-password-123"


@contextmanager
def _client(api: Api, address: tuple[str, int]) -> Iterator[TestClient]:
    with TestClient(api.app, client=address) as client:
        yield client


def _login(client: TestClient, email: str, password: str, xff: str) -> Response:
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": xff},
    )


def test_two_clients_behind_one_edge_are_counted_separately(api: Api) -> None:
    api.signup()
    api.signup(email="ben@x.test")
    with _client(api, EDGE) as ana, _client(api, EDGE) as ben:
        for _ in range(5):
            problem(_login(ana, "ana@x.test", WRONG, "203.0.113.9"), 401, "invalid_credentials")
        problem(_login(ana, "ana@x.test", WRONG, "203.0.113.9"), 429, "rate_limited")

        # Same edge address, a different viewer: not affected by ana's lockout.
        response = _login(ben, "ben@x.test", PASSWORD, "198.51.100.7")
        assert response.status_code == 200, response.text


def test_a_locked_email_stays_locked_from_another_address(api: Api) -> None:
    api.signup()
    with _client(api, EDGE) as first, _client(api, OTHER_EDGE) as other:
        for _ in range(5):
            problem(_login(first, "ana@x.test", WRONG, "203.0.113.9"), 401, "invalid_credentials")

        # Another edge and a different (spoofed) X-Forwarded-For: still locked, even with the
        # right password, so changing the client address cannot reset the limit.
        response = _login(other, "ana@x.test", PASSWORD, "6.6.6.6, 192.0.2.44")
        problem(response, 429, "rate_limited")
        assert "set-cookie" not in response.headers
