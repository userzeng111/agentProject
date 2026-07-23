#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import sys
import socket
import urllib.error
import urllib.request


def request_json(url: str, timeout: float, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def request_text(url: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def check_ok(name: str, status: int, expected: int = 200) -> None:
    if status != expected:
        raise RuntimeError(f"{name} 返回状态码异常：期望 {expected}，实际 {status}")
    print(f"[OK] {name}")


def select_novel_model(models_payload: dict, requested_model_id: str) -> str:
    requested = requested_model_id.strip()
    if requested:
        return requested
    models = models_payload.get("data")
    if not isinstance(models, list):
        raise RuntimeError("模型目录返回格式异常。")
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        features = capabilities.get("features") if isinstance(capabilities.get("features"), dict) else {}
        if (
            model_id
            and "gateway" in str(metadata.get("source") or "")
            and metadata.get("compatibility") == "verified"
            and features.get("novel_task_supported") is True
        ):
            return model_id
    raise RuntimeError("当前供应商目录没有已验证的小说任务模型，请先完成模型兼容性验证或传入 --model-id。")


def cleanup_test_task(backend: str, task_id: str, timeout: float) -> bool:
    try:
        status, _ = request_json(f"{backend}/api/tasks/{task_id}", timeout=timeout, method="DELETE")
    except Exception:  # noqa: BLE001
        return False
    return status == 200


def register_task_cleanup(backend: str, task_id: str, timeout: float):
    def cleanup() -> None:
        cleanup_test_task(backend, task_id, timeout)

    atexit.register(cleanup)
    return cleanup


def main() -> int:
    parser = argparse.ArgumentParser(description="当前仓库前后端接口与页面冒烟检查")
    parser.add_argument("--frontend-url", default="http://localhost:3000", help="前端地址")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="后端地址")
    parser.add_argument("--model-id", default="", help="显式指定本次接口自检使用的已验证小说模型")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次请求超时时间（秒）")
    parser.add_argument("--read-only", action="store_true", help="只检查健康、模型、汇总和页面路由，不创建或删除任务")
    parser.add_argument("--keep-test-task", action="store_true", help="保留本次创建的测试任务；默认在检查结束后删除")
    args = parser.parse_args()

    frontend = args.frontend_url.rstrip("/")
    backend = args.backend_url.rstrip("/")
    timeout = args.timeout

    task_id = ""
    cleanup_on_exit = None
    try:
        status, payload = request_json(f"{backend}/api/health", timeout=timeout)
        check_ok("后端健康检查", status)
        if payload.get("status") != "ok":
            raise RuntimeError("后端健康检查返回内容异常")

        status, models_payload = request_json(f"{backend}/api/models", timeout=timeout)
        check_ok("模型列表接口", status)
        try:
            model_id = select_novel_model(models_payload, args.model_id)
            print(f"[OK] 接口自检模型：{model_id}")
        except RuntimeError as exc:
            if not args.read_only:
                raise
            model_id = ""
            print(f"[WARN] 接口自检模型：{exc}")

        status, _ = request_json(f"{backend}/api/dashboard", timeout=timeout)
        check_ok("工作台汇总接口", status)

        if args.read_only:
            print("[WARN] 创建任务接口：只读模式跳过")
            route_task_id = "task_smoke_read_only"
        else:
            status, task_payload = request_json(
                f"{backend}/api/tasks",
                timeout=timeout,
                method="POST",
                payload={
                    "creative_mode": "original",
                    "novel_size": "short",
                    "prompt": "写一个临海小城中的短篇悬疑故事",
                    "genre": "悬疑",
                    "style": "冷静克制",
                    "chapter_word_min": 1800,
                    "audience": "",
                    "banned": "",
                    "title_hint": "海雾疑案",
                    "model_id": model_id,
                    "auto_review": False,
                },
            )
            check_ok("创建任务接口", status)
            task_id = task_payload.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise RuntimeError("创建任务接口未返回有效 task_id")
            route_task_id = task_id
            print(f"[OK] 已创建测试任务：{task_id}")
            if not args.keep_test_task:
                cleanup_on_exit = register_task_cleanup(backend, task_id, timeout)

            status, _ = request_json(f"{backend}/api/tasks/{task_id}", timeout=timeout)
            check_ok("任务详情接口", status)

            status, _ = request_json(f"{backend}/api/tasks/{task_id}/workspace", timeout=timeout)
            check_ok("工作台接口", status)

            status, _ = request_json(f"{backend}/api/tasks/{task_id}/supervisor", timeout=timeout)
            check_ok("Supervisor 接口", status)

        frontend_paths = [
            "/",
            "/new/",
            "/archive/",
            "/chat/",
            f"/p/{route_task_id}/",
            f"/p/{route_task_id}/?view=review",
            f"/p/{route_task_id}/?view=result",
            f"/p/{route_task_id}/?view=archive",
        ]
        for path in frontend_paths:
            status, text = request_text(f"{frontend}{path}", timeout=timeout)
            check_ok(f"前端页面 {path}", status)
            lowered = text.lower()
            if "404" in lowered and "__next" not in lowered:
                raise RuntimeError(f"前端页面 {path} 看起来返回了 404 内容")

        if task_id:
            if args.keep_test_task:
                print(f"[WARN] 按 --keep-test-task 保留测试任务：{task_id}")
            else:
                if cleanup_test_task(backend, task_id, timeout):
                    print("[OK] 删除测试任务接口")
                    if cleanup_on_exit is not None:
                        atexit.unregister(cleanup_on_exit)
                else:
                    raise RuntimeError(f"删除测试任务失败：{task_id}；进程退出时将重试一次")

        print("[OK] 全部冒烟检查通过")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"[失败] HTTP 错误：{exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"[失败] 网络错误（后端 {backend} 或前端 {frontend}）：{exc.reason}", file=sys.stderr)
        return 1
    except socket.timeout:
        print("[失败] 请求超时", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[失败] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
