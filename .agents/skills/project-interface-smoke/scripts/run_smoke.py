#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="当前仓库前后端接口与页面冒烟检查")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:3000", help="前端地址")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次请求超时时间（秒）")
    args = parser.parse_args()

    frontend = args.frontend_url.rstrip("/")
    backend = args.backend_url.rstrip("/")
    timeout = args.timeout

    try:
        status, payload = request_json(f"{backend}/api/health", timeout=timeout)
        check_ok("后端健康检查", status)
        if payload.get("status") != "ok":
            raise RuntimeError("后端健康检查返回内容异常")

        status, _ = request_json(f"{backend}/api/models", timeout=timeout)
        check_ok("模型列表接口", status)

        status, _ = request_json(f"{backend}/api/dashboard", timeout=timeout)
        check_ok("工作台汇总接口", status)

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
                "model_id": "gpt-5.4",
                "auto_review": False,
            },
        )
        check_ok("创建任务接口", status)
        task_id = task_payload.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("创建任务接口未返回有效 task_id")
        print(f"[OK] 已创建测试任务：{task_id}")

        status, _ = request_json(f"{backend}/api/tasks/{task_id}", timeout=timeout)
        check_ok("任务详情接口", status)

        status, _ = request_json(f"{backend}/api/tasks/{task_id}/workspace", timeout=timeout)
        check_ok("工作台接口", status)

        status, _ = request_json(f"{backend}/api/tasks/{task_id}/supervisor", timeout=timeout)
        check_ok("Supervisor 接口", status)

        frontend_paths = [
            "/",
            "/create/",
            "/archive/",
            "/chat/",
            f"/tasks/?id={task_id}",
            f"/review/?id={task_id}",
            f"/result/?id={task_id}",
            f"/archive/detail/?id={task_id}",
        ]
        for path in frontend_paths:
            status, text = request_text(f"{frontend}{path}", timeout=timeout)
            check_ok(f"前端页面 {path}", status)
            lowered = text.lower()
            if "404" in lowered and "__next" not in lowered:
                raise RuntimeError(f"前端页面 {path} 看起来返回了 404 内容")

        print("[OK] 全部冒烟检查通过")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"[失败] HTTP 错误：{exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"[失败] 网络错误：{exc.reason}", file=sys.stderr)
        return 1
    except socket.timeout:
        print("[失败] 请求超时", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[失败] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
