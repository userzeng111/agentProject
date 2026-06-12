from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import RateLimitMiddleware


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

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


def test_chat_requests_still_use_chat_rate_limit() -> None:
    client = TestClient(_build_test_app())

    for _ in range(20):
        response = client.post("/api/chat/completions")
        assert response.status_code == 200

    response = client.post("/api/chat/completions")

    assert response.status_code == 429
    assert response.json()["detail"] == "请求过于频繁，请稍后再试。"
