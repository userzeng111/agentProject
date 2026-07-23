#!/usr/bin/env python3
"""由 OpenAPI 清单和声明式计划驱动的 AgentProject API 验证。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from fnmatch import fnmatchcase
from pathlib import Path, PurePath
from typing import Any


HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")
SKILL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[4]
REFERENCES_DIR = SKILL_DIR / "references"
INVENTORY_PATH = REFERENCES_DIR / "api-inventory.json"
PLAN_PATH = REFERENCES_DIR / "test-plan.json"
IMPACT_PATH = REFERENCES_DIR / "module-impact-patterns.json"


def request_json(
    url: str,
    timeout: float,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url=url, method=method, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return exc.code, raw


def request_text(
    url: str,
    timeout: float,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url=url, method=method, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def request_headers(url: str, timeout: float, method: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
    request = urllib.request.Request(url=url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, {key.lower(): value for key, value in exc.headers.items()}


class Stats:
    def __init__(self) -> None:
        self.ok = 0
        self.warn = 0
        self.failed = 0
        self.skipped = 0

    def pass_(self, name: str) -> None:
        self.ok += 1
        print(f"  [OK]   {name}")

    def warning(self, name: str, reason: str) -> None:
        self.warn += 1
        print(f"  [WARN] {name} — {reason}")

    def fail(self, name: str, reason: str) -> None:
        self.failed += 1
        print(f"  [FAIL] {name} — {reason}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped += 1
        print(f"  [SKIP] {name} — {reason}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def resolve_local_ref(document: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    current: Any = document
    for part in ref[2:].split("/"):
        if not isinstance(current, dict):
            return None
        current = current.get(part.replace("~1", "/").replace("~0", "~"))
    return current


def expand_local_refs(value: Any, document: dict[str, Any], seen: frozenset[str] = frozenset()) -> Any:
    """展开本地 OpenAPI 引用，使 schema 内容变更能触发清单漂移。"""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref not in seen:
            target = resolve_local_ref(document, ref)
            if isinstance(target, (dict, list)):
                expanded = expand_local_refs(target, document, seen | {ref})
                additions = {key: item for key, item in value.items() if key != "$ref"}
                if isinstance(expanded, dict) and additions:
                    return expand_local_refs({**expanded, **additions}, document, seen | {ref})
                return expanded
        return {key: expand_local_refs(item, document, seen) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_local_refs(item, document, seen) for item in value]
    return value


def normalize_schema(value: Any) -> Any:
    """移除说明性字段，保留会影响请求和响应兼容性的 OpenAPI 信息。"""
    ignored = {"description", "summary", "title", "examples", "example", "default", "externalDocs"}
    if isinstance(value, dict):
        return {
            key: normalize_schema(item)
            for key, item in sorted(value.items())
            if key not in ignored
        }
    if isinstance(value, list):
        return sorted((normalize_schema(item) for item in value), key=canonical_json)
    return value


def normalize_parameters(path_item: dict[str, Any], operation: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    parameters: dict[tuple[str, str], dict[str, Any]] = {}
    for item in [*path_item.get("parameters", []), *operation.get("parameters", [])]:
        if not isinstance(item, dict):
            continue
        item = expand_local_refs(item, document)
        if not isinstance(item, dict):
            continue
        key = (str(item.get("in") or ""), str(item.get("name") or ""))
        parameters[key] = {
            "name": key[1],
            "in": key[0],
            "required": bool(item.get("required")),
            "schema": normalize_schema(expand_local_refs(item.get("schema") or {}, document)),
        }
    return [parameters[key] for key in sorted(parameters)]


def normalize_request_body(request_body: Any, document: dict[str, Any]) -> Any:
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content") if isinstance(request_body.get("content"), dict) else {}
    return {
        "required": bool(request_body.get("required")),
        "content": {
            media_type: normalize_schema(expand_local_refs((definition or {}).get("schema") or {}, document))
            for media_type, definition in sorted(content.items())
        },
    }


def normalize_responses(responses: Any, document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(responses, dict):
        return {}
    normalized: dict[str, Any] = {}
    for status, definition in sorted(responses.items()):
        item = definition if isinstance(definition, dict) else {}
        content = item.get("content") if isinstance(item.get("content"), dict) else {}
        headers = item.get("headers") if isinstance(item.get("headers"), dict) else {}
        normalized[str(status)] = {
            "content": {
                media_type: normalize_schema(expand_local_refs((body or {}).get("schema") or {}, document))
                for media_type, body in sorted(content.items())
            },
            "headers": {
                name: normalize_schema(expand_local_refs(header or {}, document))
                for name, header in sorted(headers.items())
            },
        }
    return normalized


def discover_inventory(openapi: dict[str, Any]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    root_security = normalize_schema(openapi.get("security") or [])
    paths = openapi.get("paths") if isinstance(openapi.get("paths"), dict) else {}
    for path, path_item_raw in sorted(paths.items()):
        if not str(path).startswith("/api/"):
            continue
        path_item = path_item_raw if isinstance(path_item_raw, dict) else {}
        for method in HTTP_METHODS:
            operation_raw = path_item.get(method)
            if not isinstance(operation_raw, dict):
                continue
            operation = operation_raw
            signature = {
                "parameters": normalize_parameters(path_item, operation, openapi),
                "request_body": normalize_request_body(expand_local_refs(operation.get("requestBody"), openapi), openapi),
                "responses": normalize_responses(expand_local_refs(operation.get("responses"), openapi), openapi),
                "security": normalize_schema(operation.get("security", path_item.get("security", root_security))),
                "deprecated": bool(operation.get("deprecated")),
            }
            operations.append(
                {
                    "method": method.upper(),
                    "path": str(path),
                    "operation_id": str(operation.get("operationId") or ""),
                    "signature": signature,
                }
            )
    operations.sort(key=lambda item: (item["path"], item["method"]))
    fingerprint = hashlib.sha256(canonical_json(operations).encode("utf-8")).hexdigest()
    return {"version": 1, "openapi_fingerprint": fingerprint, "operations": operations}


def operation_key(item: dict[str, Any]) -> str:
    return f"{item.get('method', '')} {item.get('path', '')}".strip()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"缺少配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是有效 JSON：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"配置文件根节点必须是对象：{path}")
    return payload


def compare_inventory(current: dict[str, Any], recorded: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    current_map = {operation_key(item): item for item in current.get("operations", [])}
    recorded_map = {operation_key(item): item for item in recorded.get("operations", [])}
    added = sorted(set(current_map) - set(recorded_map))
    removed = sorted(set(recorded_map) - set(current_map))
    changed = sorted(
        key
        for key in set(current_map) & set(recorded_map)
        if canonical_json(current_map[key]) != canonical_json(recorded_map[key])
    )
    return added, removed, changed


def validate_plan(current: dict[str, Any], plan: dict[str, Any]) -> tuple[list[str], list[str], list[str], dict[str, dict[str, Any]]]:
    current_keys = {operation_key(item) for item in current.get("operations", [])}
    plan_entries = plan.get("operations") if isinstance(plan.get("operations"), list) else []
    plan_map: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for entry in plan_entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("operation") or "").strip()
        if key in plan_map:
            duplicates.append(key)
        elif key:
            plan_map[key] = entry
    unclassified = sorted(
        key
        for key in current_keys
        if key not in plan_map
        or not all(plan_map[key].get(field) for field in ("module", "tier", "scenario"))
        or plan_map[key].get("required") is not True
    )
    stale = sorted(set(plan_map) - current_keys)
    return unclassified, stale, sorted(set(duplicates)), plan_map


def validate_module_coverage(plan_map: dict[str, dict[str, Any]], impact: dict[str, Any]) -> list[str]:
    modules = impact.get("modules") if isinstance(impact.get("modules"), list) else []
    impact_map = {
        str(item.get("module") or ""): item
        for item in modules
        if isinstance(item, dict) and item.get("module")
    }
    errors: list[str] = []
    for module in sorted({str(entry.get("module") or "") for entry in plan_map.values()}):
        target = impact_map.get(module)
        if target is None:
            errors.append(f"{module}（缺少影响映射）")
        elif not target.get("pytest_targets"):
            errors.append(f"{module}（缺少 pytest 目标）")
    return errors


def write_inventory(inventory: dict[str, Any]) -> None:
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    INVENTORY_PATH.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def discover_live_inventory(backend: str, timeout: float) -> dict[str, Any]:
    status, body = request_json(f"{backend}/openapi.json", timeout)
    if status != 200 or not isinstance(body, dict):
        raise ValueError(f"读取 /openapi.json 失败 status={status}")
    return discover_inventory(body)


def collect_changed_files(base_ref: str, explicit_files: list[str]) -> list[str]:
    if explicit_files:
        return sorted({item.replace("\\", "/") for item in explicit_files if item.strip()})
    if base_ref:
        command = ["git", "diff", "--name-only", f"{base_ref}...HEAD"]
    else:
        command = ["git", "diff", "--name-only", "HEAD"]
    result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise ValueError(f"无法读取 Git 变更：{result.stderr.strip() or result.stdout.strip()}")
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    files = result.stdout.splitlines()
    if not base_ref and untracked.returncode == 0:
        files.extend(untracked.stdout.splitlines())
    return sorted({item.replace("\\", "/") for item in files if item.strip()})


def path_matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    return fnmatchcase(normalized, pattern) or PurePath(normalized).match(pattern)


def select_modules(changed_files: list[str], impact: dict[str, Any]) -> list[dict[str, Any]]:
    modules = impact.get("modules") if isinstance(impact.get("modules"), list) else []
    selected: list[dict[str, Any]] = []
    for item in modules:
        if not isinstance(item, dict):
            continue
        include = [str(pattern) for pattern in item.get("include", [])]
        exclude = [str(pattern) for pattern in item.get("exclude", [])]
        if any(
            any(path_matches(path, pattern) for pattern in include)
            and not any(path_matches(path, pattern) for pattern in exclude)
            for path in changed_files
        ):
            selected.append(item)
    return selected


def run_pytest(targets: list[str], stats: Stats) -> None:
    unique_targets = sorted(dict.fromkeys(targets))
    if not unique_targets:
        stats.skip("模块测试", "当前变更未命中 API 模块")
        return
    missing = [target for target in unique_targets if not (PROJECT_ROOT / target).is_file()]
    if missing:
        stats.fail("模块测试计划", f"不存在测试目标：{', '.join(missing)}")
        return
    uv = shutil.which("uv")
    if uv:
        command = [uv, "run", "--project", str(PROJECT_ROOT / "apps/agent-runtime"), "pytest", "-q", *unique_targets]
    else:
        command = [sys.executable, "-m", "pytest", "-q", *unique_targets]
    result = subprocess.run(command, cwd=PROJECT_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    output_lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0:
        stats.pass_(f"增量 pytest：{', '.join(unique_targets)}（{output_lines[-1] if output_lines else '通过'}）")
        return
    tail = "\n".join(output_lines[-30:])
    stats.fail("增量 pytest", tail or f"退出码 {result.returncode}")


def resolve_template(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        resolved = value
        for name, replacement in variables.items():
            resolved = resolved.replace("${" + name + "}", replacement)
        return resolved
    if isinstance(value, list):
        return [resolve_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: resolve_template(item, variables) for key, item in value.items()}
    return value


def required_json_path_exists(value: Any, path: str) -> bool:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def read_json_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def run_live_requests(plan_map: dict[str, dict[str, Any]], selected_modules: set[str], backend: str, timeout: float, model_id: str, allow_gateway_unavailable: bool, stats: Stats) -> None:
    for operation, entry in sorted(plan_map.items()):
        if entry.get("module") not in selected_modules:
            continue
        live_request = entry.get("live_request")
        if not isinstance(live_request, dict):
            continue
        raw_request = canonical_json(live_request)
        if "${model_id}" in raw_request and not model_id:
            stats.fail(operation, "实时网关请求需要 --model-id")
            continue
        if "${" in raw_request.replace("${model_id}", ""):
            stats.fail(operation, "实时请求含未提供的声明式变量")
            continue
        method, path = operation.split(" ", 1)
        payload = resolve_template(live_request.get("payload"), {"model_id": model_id})
        expected_statuses = {int(status) for status in live_request.get("expected_statuses", [200])}
        expect_sse = live_request.get("expect_sse") if isinstance(live_request.get("expect_sse"), dict) else None
        if expect_sse is not None:
            status, body = request_text(f"{backend}{path}", timeout, method=method, payload=payload)
            required_events = [str(item) for item in expect_sse.get("required", [])]
            forbidden_events = [str(item) for item in expect_sse.get("forbidden", [])]
            valid = status in expected_statuses and all(item in body for item in required_events) and not any(item in body for item in forbidden_events)
        else:
            status, body = request_json(f"{backend}{path}", timeout, method=method, payload=payload)
            required_paths = [str(item) for item in live_request.get("required_json_paths", [])]
            expected_values = live_request.get("expected_json_values") if isinstance(live_request.get("expected_json_values"), dict) else {}
            valid = (
                status in expected_statuses
                and all(required_json_path_exists(body, path) for path in required_paths)
                and all(read_json_path(body, path) == (True, expected) for path, expected in expected_values.items())
            )
        if valid:
            stats.pass_(f"实时请求 {operation}")
        elif allow_gateway_unavailable and status in {502, 503, 504}:
            stats.warning(f"实时请求 {operation}", f"上游网关不可用 status={status}")
        else:
            stats.fail(f"实时请求 {operation}", f"status={status} body={str(body)[:240]}")


def run_read_only_probes(current: dict[str, Any], plan_map: dict[str, dict[str, Any]], backend: str, timeout: float, stats: Stats) -> None:
    for item in current.get("operations", []):
        key = operation_key(item)
        entry = plan_map.get(key, {})
        parameters = item.get("signature", {}).get("parameters", [])
        can_probe = item.get("method") == "GET" and "{" not in str(item.get("path")) and not any(param.get("required") for param in parameters)
        if entry.get("tier") != "read-only" or not can_probe:
            continue
        status, _ = request_json(f"{backend}{item['path']}", timeout)
        if 200 <= status < 300:
            stats.pass_(f"只读探测 {key}")
        else:
            stats.fail(f"只读探测 {key}", f"status={status}")


def run_cors_probe(current: dict[str, Any], backend: str, origin: str, timeout: float, stats: Stats) -> None:
    static_get = next(
        (
            item
            for item in current.get("operations", [])
            if item.get("method") == "GET"
            and "{" not in str(item.get("path"))
            and not any(parameter.get("required") for parameter in item.get("signature", {}).get("parameters", []))
        ),
        None,
    )
    if static_get is None:
        stats.fail("CORS", "OpenAPI 中没有可安全预检的 GET 接口")
        return
    requested_methods = sorted({item.get("method") for item in current.get("operations", []) if item.get("method") not in {"HEAD", "OPTIONS"}})
    status, headers = request_headers(
        f"{backend}{static_get['path']}",
        timeout,
        "OPTIONS",
        {
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type, Authorization, X-Request-ID",
        },
    )
    allowed_methods = {item.strip().upper() for item in headers.get("access-control-allow-methods", "").split(",")}
    allow_headers = {item.strip().lower() for item in headers.get("access-control-allow-headers", "").split(",")}
    required_headers = {"content-type", "authorization", "x-request-id"}
    if (
        status in {200, 204}
        and headers.get("access-control-allow-origin") == origin
        and set(requested_methods).issubset(allowed_methods)
        and required_headers.issubset(allow_headers)
    ):
        stats.pass_(f"CORS：{origin}")
    else:
        stats.fail("CORS", f"status={status} origin={headers.get('access-control-allow-origin', '')} methods={headers.get('access-control-allow-methods', '')} headers={headers.get('access-control-allow-headers', '')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAPI 清单驱动的 AgentProject API 增量验证")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="后端地址")
    parser.add_argument("--frontend-url", default="", help="前端 Origin，仅用于 CORS 预检")
    parser.add_argument("--mode", choices=("check", "sync", "changed", "full", "read-only"), default="changed", help="check 只校验清单；sync 更新清单；changed 仅测受影响模块；full 测全部模块；read-only 只发安全 GET")
    parser.add_argument("--read-only", action="store_true", help="兼容旧命令，等同 --mode read-only")
    parser.add_argument("--changed-files", action="append", default=[], help="指定变更文件，可重复传入")
    parser.add_argument("--base-ref", default="", help="增量比较基线，使用 git diff <base-ref>...HEAD")
    parser.add_argument("--model-id", default="", help="实时网关声明式请求使用的模型 ID")
    parser.add_argument("--live-gateway", action="store_true", help="允许执行计划中声明的真实模型/聊天请求")
    parser.add_argument("--allow-gateway-unavailable", action="store_true", help="仅实时网关请求可将 502/503/504 记为警告")
    parser.add_argument("--timeout", type=float, default=10.0, help="单次 HTTP 请求超时（秒）")
    args = parser.parse_args()
    mode = "read-only" if args.read_only else args.mode
    backend = args.backend_url.rstrip("/")
    stats = Stats()

    print("=" * 60)
    print(f"OpenAPI API 验证：{mode}")
    print(f"后端: {backend}")
    print("=" * 60)

    try:
        current = discover_live_inventory(backend, args.timeout)
        recorded = load_json(INVENTORY_PATH)
        plan = load_json(PLAN_PATH)
        impact = load_json(IMPACT_PATH)
    except (urllib.error.URLError, socket.timeout) as exc:
        print(f"[FAIL] 后端服务不可达：{exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        stats.fail("API 清单", str(exc))
        print(f"测试完成：✅ {stats.ok} 通过 ⚠️ {stats.warn} 警告 ⏭️ {stats.skipped} 跳过 ❌ {stats.failed} 失败")
        return 1

    added, removed, changed = compare_inventory(current, recorded)
    if mode == "sync":
        write_inventory(current)
        stats.pass_(f"已同步 API 清单：{len(current['operations'])} 个操作")
        if added or removed or changed:
            stats.fail("清单待审查", "; ".join(filter(None, [f"新增 {len(added)}", f"删除 {len(removed)}", f"变更 {len(changed)}"])))
    elif added or removed or changed:
        details = "; ".join(filter(None, [f"新增 {len(added)}", f"删除 {len(removed)}", f"变更 {len(changed)}"]))
        stats.fail("OpenAPI 漂移", details)
        for label, items in (("新增", added), ("删除", removed), ("变更", changed)):
            for item in items:
                print(f"    {label}: {item}")
    else:
        stats.pass_(f"OpenAPI 清单一致：{len(current['operations'])} 个操作")

    unclassified, stale, duplicates, plan_map = validate_plan(current, plan)
    for label, items in (("未分类接口", unclassified), ("过期测试计划", stale), ("重复测试计划", duplicates)):
        if items:
            stats.fail(label, ", ".join(items))
        else:
            stats.pass_(f"{label}：无")
    module_errors = validate_module_coverage(plan_map, impact)
    if module_errors:
        stats.fail("模块测试映射", ", ".join(module_errors))
    else:
        stats.pass_("模块测试映射：完整")

    if stats.failed or mode in {"check", "sync"}:
        print(f"测试完成：✅ {stats.ok} 通过 ⚠️ {stats.warn} 警告 ⏭️ {stats.skipped} 跳过 ❌ {stats.failed} 失败")
        return 1 if stats.failed else 0

    if mode == "read-only":
        run_read_only_probes(current, plan_map, backend, args.timeout, stats)
    else:
        if mode == "changed":
            try:
                changed_files = collect_changed_files(args.base_ref, args.changed_files)
            except ValueError as exc:
                stats.fail("读取变更", str(exc))
                changed_files = []
            selected = select_modules(changed_files, impact)
        else:
            selected = impact.get("modules")
        selected_modules = {str(item.get("module")) for item in selected if isinstance(item, dict)}
        if mode == "changed":
            print(f"受影响模块：{', '.join(sorted(selected_modules)) or '无'}")
        else:
            print(f"全量模块：{', '.join(sorted(selected_modules)) or '无'}")
        targets = [target for item in selected if isinstance(item, dict) for target in item.get("pytest_targets", [])]
        run_pytest(targets, stats)
        if args.live_gateway:
            run_live_requests(plan_map, selected_modules, backend, args.timeout, args.model_id, args.allow_gateway_unavailable, stats)

    if args.frontend_url:
        run_cors_probe(current, backend, args.frontend_url.rstrip("/"), args.timeout, stats)

    print(f"测试完成：✅ {stats.ok} 通过 ⚠️ {stats.warn} 警告 ⏭️ {stats.skipped} 跳过 ❌ {stats.failed} 失败")
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
