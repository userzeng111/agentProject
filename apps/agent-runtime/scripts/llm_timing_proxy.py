from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


LOGGER = logging.getLogger("llm_timing_proxy")
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
REQUEST_ID_HEADER_CANDIDATES = (
    "x-request-id",
    "request-id",
    "x-correlation-id",
    "openai-request-id",
)
REQUEST_ID_QUERY_CANDIDATES = ("request_id", "requestId", "req_id")


class ProxyConfig:
    def __init__(
        self,
        upstream_base_url: str,
        *,
        connect_timeout_seconds: float = 30.0,
        read_timeout_seconds: float = 300.0,
        buffer_size: int = 65536,
    ) -> None:
        parsed = urlsplit(upstream_base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("upstream_base_url 只支持 http 或 https")
        if not parsed.netloc:
            raise ValueError("upstream_base_url 必须包含主机与端口")
        self.upstream_base_url = upstream_base_url.rstrip("/")
        self.connect_timeout_seconds = connect_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds
        self.buffer_size = buffer_size


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], config: ProxyConfig) -> None:
        self.config = config
        super().__init__(server_address, _TimingProxyHandler)


class _TimingProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy_request()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _proxy_request(self) -> None:
        config = self.server.config
        request_start = _utc_now_iso()
        started_at = time.perf_counter()
        parsed_request = urlsplit(self.path)
        request_body = self._read_request_body()
        request_id = _extract_request_id(self.headers, parsed_request.query)
        model = _extract_model(request_body, self.headers.get("Content-Type", ""))
        status_code = 502
        response_bytes = 0
        first_byte_ms: int | None = None
        connection: http.client.HTTPConnection | http.client.HTTPSConnection | None = None

        try:
            connection = _build_upstream_connection(config)
            upstream_path = _build_upstream_path(config.upstream_base_url, self.path)
            headers = _prepare_upstream_headers(self.headers)
            body = request_body if request_body else None
            connection.request(self.command, upstream_path, body=body, headers=headers)
            upstream_response = connection.getresponse()

            status_code = upstream_response.status
            self.send_response(upstream_response.status, upstream_response.reason)
            for header_name, header_value in upstream_response.getheaders():
                if header_name.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(header_name, header_value)
            self.end_headers()

            if self.command != "HEAD":
                while True:
                    chunk = upstream_response.read(config.buffer_size)
                    if not chunk:
                        break
                    if first_byte_ms is None:
                        first_byte_ms = _elapsed_ms(started_at)
                    response_bytes += len(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()

            if first_byte_ms is None:
                first_byte_ms = _elapsed_ms(started_at)
        except Exception:
            self.close_connection = True
            body = "上游请求失败".encode("utf-8")
            status_code = 502
            response_bytes = len(body)
            if first_byte_ms is None:
                first_byte_ms = _elapsed_ms(started_at)
            self.send_response(status_code, "Upstream Request Failed")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
                self.wfile.flush()
        finally:
            if connection is not None:
                connection.close()

        event = {
            "request_start": request_start,
            "first_byte_ms": first_byte_ms,
            "duration_ms": _elapsed_ms(started_at),
            "status_code": status_code,
            "response_bytes": response_bytes,
            "method": self.command,
            "path": parsed_request.path or "/",
            "model": model,
            "request_id": request_id,
        }
        LOGGER.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))

    def _read_request_body(self) -> bytes:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            return b""
        try:
            size = int(content_length)
        except ValueError:
            return b""
        if size <= 0:
            return b""
        return self.rfile.read(size)


def create_server(server_address: tuple[str, int], config: ProxyConfig) -> ThreadingHTTPServer:
    return _ProxyServer(server_address, config)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = ProxyConfig(
        upstream_base_url=args.upstream_base_url,
        connect_timeout_seconds=args.connect_timeout_seconds,
        read_timeout_seconds=args.read_timeout_seconds,
    )
    server = create_server((args.host, args.port), config)
    LOGGER.info(
        json.dumps(
            {
                "event": "proxy_started",
                "listen": f"{args.host}:{server.server_port}",
                "upstream_base_url": config.upstream_base_url,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地 LLM 反向代理与耗时采样脚本")
    parser.add_argument(
        "--host",
        default=os.getenv("LLM_TIMING_PROXY_HOST", "localhost"),
        help="监听地址，默认读取 LLM_TIMING_PROXY_HOST 或 localhost",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("LLM_TIMING_PROXY_PORT", "18080")),
        help="监听端口，默认读取 LLM_TIMING_PROXY_PORT 或 18080",
    )
    parser.add_argument(
        "--upstream-base-url",
        default=os.getenv("LLM_TIMING_PROXY_UPSTREAM_BASE_URL", ""),
        help="上游基址，默认读取 LLM_TIMING_PROXY_UPSTREAM_BASE_URL",
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=float(os.getenv("LLM_TIMING_PROXY_CONNECT_TIMEOUT_SECONDS", "30")),
        help="连接超时秒数",
    )
    parser.add_argument(
        "--read-timeout-seconds",
        type=float,
        default=float(os.getenv("LLM_TIMING_PROXY_READ_TIMEOUT_SECONDS", "300")),
        help="读取超时秒数",
    )
    args = parser.parse_args()
    if not args.upstream_base_url:
        parser.error("必须提供 --upstream-base-url 或 LLM_TIMING_PROXY_UPSTREAM_BASE_URL")
    return args


def _build_upstream_connection(
    config: ProxyConfig,
) -> http.client.HTTPConnection | http.client.HTTPSConnection:
    parsed = urlsplit(config.upstream_base_url)
    timeout = max(config.connect_timeout_seconds, config.read_timeout_seconds)
    connection_class = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    return connection_class(parsed.hostname, parsed.port, timeout=timeout)


def _prepare_upstream_headers(headers: Any) -> dict[str, str]:
    prepared: dict[str, str] = {}
    for header_name, header_value in headers.items():
        if header_name.lower() in HOP_BY_HOP_HEADERS or header_name.lower() == "host":
            continue
        prepared[header_name] = header_value
    return prepared


def _build_upstream_path(upstream_base_url: str, request_path: str) -> str:
    upstream = urlsplit(upstream_base_url)
    incoming = urlsplit(request_path)
    base_path = upstream.path.rstrip("/")
    suffix_path = incoming.path or "/"
    if base_path and suffix_path.startswith("/"):
        merged_path = f"{base_path}{suffix_path}"
    else:
        merged_path = f"{base_path}/{suffix_path}".replace("//", "/")
    if incoming.query:
        return f"{merged_path}?{incoming.query}"
    return merged_path


def _extract_request_id(headers: Any, query: str) -> str | None:
    for header_name in REQUEST_ID_HEADER_CANDIDATES:
        value = headers.get(header_name)
        if value:
            return value
    query_params = parse_qs(query, keep_blank_values=False)
    for key in REQUEST_ID_QUERY_CANDIDATES:
        values = query_params.get(key)
        if values:
            return values[0]
    return None


def _extract_model(request_body: bytes, content_type: str) -> str | None:
    if not request_body:
        return None
    if "json" not in content_type.lower():
        return None
    try:
        payload = json.loads(request_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("model"), str):
        return payload["model"]
    return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


if __name__ == "__main__":
    main()
