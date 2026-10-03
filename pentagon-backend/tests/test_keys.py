import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import nvidia_client


@pytest.fixture
def api_client():
    with TestClient(app) as client:
        yield client


def test_validate_key_success_returns_model_ids(api_client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer nvapi-test-secret-1234"
        return httpx.Response(
            200,
            json={"data": [{"id": f"model-{index}"} for index in range(7)]},
            request=request,
        )

    monkeypatch.setattr(
        nvidia_client,
        "_new_async_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = api_client.post(
        "/api/keys/validate",
        json={"api_key": "nvapi-test-secret-1234"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "model_count": 7,
        "sample_models": [f"model-{index}" for index in range(5)],
    }
    assert "nvapi-test-secret-1234" not in response.text


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [
        (401, "The NVIDIA API key was rejected. Check the key and try again."),
        (429, "NVIDIA rate-limited this request. Please wait and try again."),
    ],
)
def test_validate_key_reports_safe_failure(
    api_client,
    monkeypatch,
    status_code: int,
    reason: str,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request)

    monkeypatch.setattr(
        nvidia_client,
        "_new_async_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = api_client.post(
        "/api/keys/validate",
        json={"api_key": "nvapi-test-secret-1234"},
    )

    assert response.status_code == 200
    assert response.json() == {"valid": False, "reason": reason}
    assert "nvapi-test-secret-1234" not in response.text
