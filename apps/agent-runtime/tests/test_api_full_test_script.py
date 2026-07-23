from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator
from urllib.parse import urlsplit


def _script_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / ".agents"
        / "skills"
        / "api-full-test"
        / "scripts"
        / "run_full_test.py"
    )


def _load_script_module():
    spec = importlib.util.spec_from_file_location("api_full_test_script", _script_path())
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _openapi_for(*names: str) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "离线评测", "version": "1"},
        "paths": {
            f"/api/{name}": {
                "get": {
                    "operationId": f"get_{name}",
                    "responses": {"200": {"description": "OK"}},
                }
            }
            for name in names
        },
    }


def _inventory_for(*names: str) -> dict:
    operations = []
    for name in sorted(names):
        operations.append(
            {
                "method": "GET",
                "path": f"/api/{name}",
                "operation_id": f"get_{name}",
                "signature": {
                    "parameters": [],
                    "request_body": None,
                    "responses": {"200": {"content": {}, "headers": {}}},
                    "security": [],
                    "deprecated": False,
                },
            }
        )
    return {"version": 1, "openapi_fingerprint": "离线夹具", "operations": operations}


def _plan_for(*names: str) -> dict:
    return {
        "version": 1,
        "operations": [
            {
                "operation": f"GET /api/{name}",
                "module": name,
                "tier": "read-only" if name == "health" else "state-machine",
                "scenario": f"{name}-scenario",
                "required": True,
                "live_request": {"expected_statuses": [200]},
            }
            for name in names
        ],
    }


def _impact_for(*names: str) -> dict:
    return {
        "version": 1,
        "modules": [
            {
                "module": name,
                "include": [f"apps/agent-runtime/app/api/{name}.py"],
                "pytest_targets": ["tests/test_incremental_stub.py"],
            }
            for name in names
        ],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_isolated_skill(
    tmp_path: Path,
    *,
    inventory: dict,
    plan: dict,
    impact: dict,
) -> tuple[Path, Path, Path]:
    skill_dir = tmp_path / ".agents" / "skills" / "api-full-test"
    script = skill_dir / "scripts" / "run_full_test.py"
    references = skill_dir / "references"
    script.parent.mkdir(parents=True)
    references.mkdir()
    shutil.copy2(_script_path(), script)
    stub_test = tmp_path / "tests" / "test_incremental_stub.py"
    stub_test.parent.mkdir()
    stub_test.write_text("def test_incremental_stub() -> None:\n    assert True\n", encoding="utf-8")

    inventory_path = references / "api-inventory.json"
    plan_path = references / "test-plan.json"
    _write_json(inventory_path, inventory)
    _write_json(plan_path, plan)
    _write_json(references / "module-impact-patterns.json", impact)
    return script, inventory_path, plan_path


@contextmanager
def _serve_openapi(openapi: dict) -> Iterator[tuple[str, list[tuple[str, str]]]]:
    requests: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_json(self, status: int, payload: dict) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            requests.append(("GET", path))
            if path == "/openapi.json":
                self._send_json(200, openapi)
            elif path in openapi["paths"]:
                self._send_json(200, {"path": path})
            else:
                self._send_json(404, {"detail": "不存在"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _run(script: Path, backend: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = "/usr/bin:/bin"
    return subprocess.run(
        [sys.executable, str(script), "--backend-url", backend, "--timeout", "1", *arguments],
        cwd=script.parents[4],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )


def test_unclassified_openapi_operation_blocks_check_and_full_before_live_requests(tmp_path: Path) -> None:
    script, _, _ = _prepare_isolated_skill(
        tmp_path,
        inventory=_inventory_for("health"),
        plan=_plan_for("health"),
        impact=_impact_for("health"),
    )

    with _serve_openapi(_openapi_for("health", "new-operation")) as (backend, requests):
        check = _run(script, backend, "--mode", "check")
        assert check.returncode == 1, check.stdout + check.stderr
        assert "OpenAPI 漂移" in check.stdout
        assert "未分类接口" in check.stdout
        assert requests == [("GET", "/openapi.json")]

        requests.clear()
        full = _run(script, backend, "--mode", "full", "--live-gateway")
        assert full.returncode == 1, full.stdout + full.stderr
        assert "未分类接口" in full.stdout
        assert requests == [("GET", "/openapi.json")]


def test_sync_updates_only_api_inventory_and_keeps_unclassified_gate(tmp_path: Path) -> None:
    plan = _plan_for("health")
    script, inventory_path, plan_path = _prepare_isolated_skill(
        tmp_path,
        inventory=_inventory_for("health"),
        plan=plan,
        impact=_impact_for("health"),
    )

    with _serve_openapi(_openapi_for("health", "new-operation")) as (backend, requests):
        completed = _run(script, backend, "--mode", "sync")

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "已同步 API 清单" in completed.stdout
    assert "未分类接口" in completed.stdout
    assert requests == [("GET", "/openapi.json")]
    assert [entry["path"] for entry in json.loads(inventory_path.read_text(encoding="utf-8"))["operations"]] == [
        "/api/health",
        "/api/new-operation",
    ]
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan


def test_sync_keeps_contract_only_change_in_review_gate(tmp_path: Path) -> None:
    script, inventory_path, _ = _prepare_isolated_skill(
        tmp_path,
        inventory=_inventory_for("health"),
        plan=_plan_for("health"),
        impact=_impact_for("health"),
    )
    changed_openapi = _openapi_for("health")
    changed_openapi["paths"]["/api/health"]["get"]["responses"]["200"]["content"] = {
        "application/json": {"schema": {"type": "object", "properties": {"status": {"type": "string"}}}}
    }

    with _serve_openapi(changed_openapi) as (backend, _requests):
        completed = _run(script, backend, "--mode", "sync")

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "清单待审查" in completed.stdout
    assert json.loads(inventory_path.read_text(encoding="utf-8"))["operations"][0]["signature"]["responses"]["200"]["content"]


def test_changed_executes_only_impacted_modules_while_full_executes_every_module(tmp_path: Path) -> None:
    names = ("health", "alpha", "beta")
    script, _, _ = _prepare_isolated_skill(
        tmp_path,
        inventory=_inventory_for(*names),
        plan=_plan_for(*names),
        impact=_impact_for(*names),
    )

    with _serve_openapi(_openapi_for(*names)) as (backend, requests):
        changed = _run(
            script,
            backend,
            "--mode",
            "changed",
            "--changed-files",
            "apps/agent-runtime/app/api/alpha.py",
            "--live-gateway",
        )
        assert changed.returncode == 0, changed.stdout + changed.stderr
        assert ("GET", "/api/alpha") in requests
        assert ("GET", "/api/beta") not in requests
        assert ("GET", "/api/health") not in requests

        requests.clear()
        full = _run(script, backend, "--mode", "full", "--live-gateway")
        assert full.returncode == 0, full.stdout + full.stderr
        assert {path for method, path in requests if method == "GET"} == {
            "/openapi.json",
            "/api/health",
            "/api/alpha",
            "/api/beta",
        }


def test_read_only_mode_never_uses_non_read_only_operations(tmp_path: Path) -> None:
    names = ("health", "alpha")
    script, _, _ = _prepare_isolated_skill(
        tmp_path,
        inventory=_inventory_for(*names),
        plan=_plan_for(*names),
        impact=_impact_for(*names),
    )

    with _serve_openapi(_openapi_for(*names)) as (backend, requests):
        completed = _run(script, backend, "--mode", "read-only")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert ("GET", "/api/health") in requests
    assert ("GET", "/api/alpha") not in requests


def test_live_sse_rejects_http_200_error_event() -> None:
    module = _load_script_module()
    original_request_text = module.request_text
    module.request_text = lambda *_args, **_kwargs: (200, "event: chat.error\ndata: {\"message\": \"网关失败\"}\n\n")
    try:
        stats = module.Stats()
        module.run_live_requests(
            {
                "POST /api/chat/stream": {
                    "module": "chat",
                    "live_request": {
                        "payload": {"model": "${model_id}"},
                        "expected_statuses": [200],
                        "expect_sse": {
                            "required": ["event: chat.chunk", "event: chat.done"],
                            "forbidden": ["event: chat.error"],
                        },
                    },
                }
            },
            {"chat"},
            "http://example.test",
            1,
            "verified-model",
            False,
            stats,
        )
    finally:
        module.request_text = original_request_text

    assert stats.failed == 1
