"""The mobile shells must be able to reach the API from their own origin.

The iOS and Android apps load the bundle inside a native WebView, so they are a
different origin from this API. Every chat request would otherwise be blocked
at the preflight, before a route ever ran, which makes the phone build look
broken with nothing in the server logs to explain it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


CAPACITOR_ORIGINS = ["capacitor://localhost", "http://localhost"]


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("origin", CAPACITOR_ORIGINS)
def test_preflight_from_a_native_shell_origin_is_allowed(client, origin):
    response = client.options(
        "/api/chat",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,accept",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_preflight_from_an_unrelated_origin_is_refused(client):
    response = client.options(
        "/api/chat",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_actual_request_carries_the_allow_origin_header(client):
    user_id = f"cors-test-{uuid4()}"
    response = client.get(
        "/api/models",
        params={"user_id": user_id},
        headers={"Origin": "capacitor://localhost"},
    )

    # The route itself may reject the user for having no key; what matters is
    # that the browser is handed the header needed to read the response.
    assert response.headers.get("access-control-allow-origin") == "capacitor://localhost"


def test_streamed_audio_headers_are_exposed_to_the_shell(client):
    """The reply audio is read from these headers, which fetch must expose.

    ``Access-Control-Expose-Headers`` belongs on the real response rather than
    the preflight, since that is the response whose headers the script reads.
    """
    response = client.get(
        "/api/models",
        params={"user_id": f"cors-expose-{uuid4()}"},
        headers={"Origin": "http://localhost"},
    )

    exposed = response.headers.get("access-control-expose-headers", "")
    for header in ("X-Audio-Format", "X-Audio-Sample-Rate", "X-Audio-Channels"):
        assert header in exposed