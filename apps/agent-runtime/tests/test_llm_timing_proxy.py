from __future__ import annotations

import http.client
import importlib.util
import json
import logging
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "llm_timing_proxy.py"
)


def _load_proxy_module() -> Any:
    spec = importlib.util.spec_from_file_location("llm_timing_proxy", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 llm_timing_proxy 脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json_log(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    deadline = time.time() + 1.0
    while time.time() < deadline:
        for record in reversed(caplog.records):
            if record.name == "llm_timing_proxy":
                return json.loads(record.getMessage())
        time.sleep(0.01)
    raise AssertionError("未捕获到 llm_timing_proxy 日志")


@dataclass
class _ServerHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class _UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._write_response()

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        self.server.last_body = self.rfile.read(content_length)
        self._write_response()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_response(self) -> None:
        response = self.server.response_bytes
        self.send_response(self.server.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        first = response[: self.server.first_chunk_size]
        rest = response[self.server.first_chunk_size :]
        if first:
            self.wfile.write(first)
            self.wfile.flush()
        if self.server.delay_after_first_chunk > 0:
            time.sleep(self.server.delay_after_first_chunk)
        if rest:
            self.wfile.write(rest)
            self.wfile.flush()


def _start_upstream_server(
    *,
    response_body: bytes,
    status_code: int = 200,
    first_chunk_size: int = 1,
    delay_after_first_chunk: float = 0.05,
) -> _ServerHandle:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    server.response_bytes = response_body
    server.status_code = status_code
    server.first_chunk_size = first_chunk_size
    server.delay_after_first_chunk = delay_after_first_chunk
    server.last_body = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return _ServerHandle(server=server, thread=thread)


def test_proxy_records_only_safe_http_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proxy_module = _load_proxy_module()
    upstream = _start_upstream_server(
        response_body=b'{"result":"secret-response-body"}',
        first_chunk_size=5,
    )
    proxy = None

    try:
        config = proxy_module.ProxyConfig(
            upstream_base_url=f"http://127.0.0.1:{upstream.server.server_port}",
        )
        proxy_server = proxy_module.create_server(("127.0.0.1", 0), config)
        thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
        thread.start()
        proxy = _ServerHandle(server=proxy_server, thread=thread)

        with caplog.at_level(logging.INFO, logger="llm_timing_proxy"):
            conn = http.client.HTTPConnection("127.0.0.1", proxy_server.server_port, timeout=5)
            payload = json.dumps(
                {
                    "model": "glm-5.1",
                    "messages": [{"role": "user", "content": "绝不能被记录的提示词"}],
                }
            ).encode("utf-8")
            conn.request(
                "POST",
                "/v1/chat/completions?unused=1",
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(payload)),
                    "X-Request-Id": "req-header-1",
                },
            )
            response = conn.getresponse()
            body = response.read()
            conn.close()

        assert response.status == 200
        assert body == b'{"result":"secret-response-body"}'
        assert upstream.server.last_body == payload

        event = _read_json_log(caplog)
        assert event["method"] == "POST"
        assert event["path"] == "/v1/chat/completions"
        assert event["status_code"] == 200
        assert event["response_bytes"] == len(body)
        assert event["model"] == "glm-5.1"
        assert event["request_id"] == "req-header-1"
        assert event["duration_ms"] >= event["first_byte_ms"] >= 0
        assert event["request_start"]

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "绝不能被记录的提示词" not in messages
        assert "secret-response-body" not in messages
    finally:
        if proxy is not None:
            proxy.close()
        upstream.close()


def test_proxy_falls_back_to_query_request_id_and_missing_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proxy_module = _load_proxy_module()
    upstream = _start_upstream_server(response_body=b"ok", delay_after_first_chunk=0.0)
    proxy = None

    try:
        config = proxy_module.ProxyConfig(
            upstream_base_url=f"http://127.0.0.1:{upstream.server.server_port}",
        )
        proxy_server = proxy_module.create_server(("127.0.0.1", 0), config)
        thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
        thread.start()
        proxy = _ServerHandle(server=proxy_server, thread=thread)

        with caplog.at_level(logging.INFO, logger="llm_timing_proxy"):
            conn = http.client.HTTPConnection("127.0.0.1", proxy_server.server_port, timeout=5)
            conn.request("GET", "/health?request_id=req-query-1")
            response = conn.getresponse()
            body = response.read()
            conn.close()

        assert response.status == 200
        assert body == b"ok"

        event = _read_json_log(caplog)
        assert event["method"] == "GET"
        assert event["path"] == "/health"
        assert event["status_code"] == 200
        assert event["response_bytes"] == 2
        assert event["model"] is None
        assert event["request_id"] == "req-query-1"
    finally:
        if proxy is not None:
            proxy.close()
        upstream.close()
