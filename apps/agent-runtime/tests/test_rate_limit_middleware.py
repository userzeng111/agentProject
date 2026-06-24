from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import RateLimitMiddleware


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.options("/api/ping")
    def ping_options() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health")
    def api_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/chat/completions")
    def chat_completions() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _build_configured_test_app(general_limit: int, chat_limit: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, general_limit=general_limit, chat_limit=chat_limit)

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/chat/completions")
    def chat_completions() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_general_api_requests_do_not_consume_chat_rate_limit() -> None:
    client = TestClient(_build_test_app())

    for _ in range(20):
        response = client.get("/api/ping")
        assert response.status_code == 200

    response = client.post("/api/chat/completions")

    assert response.status_code == 200


def test_rate_limit_accepts_configured_thresholds() -> None:
    client = TestClient(_build_configured_test_app(general_limit=2, chat_limit=1))

    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping").status_code == 429

    assert client.post("/api/chat/completions").status_code == 200
    assert client.post("/api/chat/completions").status_code == 429


def test_chat_requests_still_use_chat_rate_limit() -> None:
    client = TestClient(_build_test_app())

    for _ in range(20):
        response = client.post("/api/chat/completions")
        assert response.status_code == 200

    response = client.post("/api/chat/completions")

    assert response.status_code == 429
    assert response.json()["detail"] == "请求过于频繁，请稍后再试。"


def test_cors_preflight_requests_are_not_rate_limited() -> None:
    client = TestClient(_build_test_app())

    for _ in range(60):
        response = client.get("/api/ping")
        assert response.status_code == 200

    response = client.options("/api/ping")

    assert response.status_code == 200


def test_api_health_is_not_rate_limited() -> None:
    client = TestClient(_build_test_app())

    for _ in range(60):
        response = client.get("/api/ping")
        assert response.status_code == 200

    response = client.get("/api/health")

    assert response.status_code == 200
