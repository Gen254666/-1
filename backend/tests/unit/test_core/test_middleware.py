from fastapi.testclient import TestClient

from app.main import create_app


def test_request_id_is_echoed() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz", headers={"X-Request-ID": "req-abc"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-abc"


def test_request_id_is_generated_when_missing() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
