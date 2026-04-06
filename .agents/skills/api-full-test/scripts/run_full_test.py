#!/usr/bin/env python3
"""全量 API 接口冒烟测试脚本"""
from __future__ import annotations

import argparse
import json
import sys
import socket
import time
import urllib.error
import urllib.request


# ── 工具函数 ──

def request_json(
    url: str, timeout: float, method: str = "GET", payload: dict | None = None, headers: dict | None = None,
) -> tuple[int, dict | None]:
    data = None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, method=method, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = None
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            pass
        return exc.code, body


def request_text(url: str, timeout: float, method: str = "GET", payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


# ── 测试统计 ──

class Stats:
    def __init__(self):
        self.ok = 0
        self.warn = 0
        self.fail = 0

    def pass_(self, name: str):
        self.ok += 1
        print(f"  [OK]   {name}")

    def warning(self, name: str, reason: str):
        self.warn += 1
        print(f"  [WARN] {name} — {reason}")

    def fail(self, name: str, reason: str):
        self.fail += 1
        print(f"  [FAIL] {name} — {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description="全量 API 接口冒烟测试")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="后端地址")
    parser.add_argument("--frontend-url", default=None, help="前端地址（不传则跳过前端测试）")
    parser.add_argument("--timeout", type=float, default=10.0, help="单次请求超时（秒）")
    args = parser.parse_args()

    backend = args.backend_url.rstrip("/")
    frontend = (args.frontend_url or "").rstrip("/")
    timeout = args.timeout
    stats = Stats()

    print("=" * 60)
    print("全量 API 接口冒烟测试")
    print(f"后端: {backend}")
    if frontend:
        print(f"前端: {frontend}")
    print("=" * 60)

    # ── 1. 基础接口 ──
    print("\n── 1. 基础接口 ──")

    status, body = request_json(f"{backend}/api/health", timeout)
    if status == 200 and body and body.get("status") == "ok":
        stats.pass_("/api/health")
    else:
        stats.fail("/api/health", f"status={status}, body={body}")

    status, body = request_json(f"{backend}/api/models", timeout)
    if status == 200 and body and isinstance(body.get("data"), list):
        stats.pass_(f"/api/models ({len(body['data'])} 个模型)")
    else:
        stats.fail(f"/api/models", f"status={status}")

    status, body = request_json(f"{backend}/api/dashboard", timeout)
    if status == 200 and body:
        ct = len(body.get("continue_tasks", []))
        rt = len(body.get("running_tasks", []))
        ft = len(body.get("failed_tasks", []))
        stats.pass_(f"/api/dashboard (待处理:{ct} 运行中:{rt} 失败:{ft})")
    else:
        stats.fail("/api/dashboard", f"status={status}")

    # ── 2. 任务 CRUD ──
    print("\n── 2. 任务 CRUD ──")

    status, body = request_json(f"{backend}/api/tasks", timeout, method="POST", payload={
        "mode": "short_story",
        "prompt": "接口自检测试任务",
        "genre": "玄幻",
        "style": "轻松",
        "target_words": 1000,
        "audience": "年轻人",
        "banned": "",
        "title_hint": "自检测试",
    })
    task_id = None
    if status == 200 and body and body.get("id"):
        task_id = body["id"]
        stats.pass_(f"POST /api/tasks → {task_id}")
    else:
        stats.fail("POST /api/tasks", f"status={status}")

    if task_id:
        status, body = request_json(f"{backend}/api/tasks/{task_id}", timeout)
        if status == 200 and body and body.get("id") == task_id:
            stats.pass_(f"GET /api/tasks/{task_id}")
        else:
            stats.fail(f"GET /api/tasks/{task_id}", f"status={status}")

        status, body = request_json(f"{backend}/api/tasks/{task_id}/workspace", timeout)
        if status == 200 and body and body.get("meta"):
            tabs = body.get("available_tabs", [])
            stats.pass_(f"GET /api/tasks/{task_id}/workspace (tabs: {tabs})")
        else:
            stats.fail(f"GET /api/tasks/{task_id}/workspace", f"status={status}")

        status, body = request_json(f"{backend}/api/tasks/{task_id}/supervisor", timeout)
        if status == 200 and body:
            subs = len(body.get("subtasks", []))
            stats.pass_(f"GET /api/tasks/{task_id}/supervisor ({subs} 子任务)")
        else:
            stats.fail(f"GET /api/tasks/{task_id}/supervisor", f"status={status}")

        # review / result / chapters / artifacts — 对 created 状态的任务
        for ep, expected_ok in [
            ("review", False),   # created 状态无审核数据
            ("result", False),   # created 状态无结果
            ("chapters", True),
            ("artifacts", True),
        ]:
            status, _ = request_json(f"{backend}/api/tasks/{task_id}/{ep}", timeout)
            if expected_ok and status == 200:
                stats.pass_(f"GET /api/tasks/{task_id}/{ep}")
            elif not expected_ok and status in (400, 404):
                stats.warning(f"GET /api/tasks/{task_id}/{ep}", f"status={status}（任务未到该阶段，预期行为）")
            elif status == 200:
                stats.pass_(f"GET /api/tasks/{task_id}/{ep}")
            else:
                stats.fail(f"GET /api/tasks/{task_id}/{ep}", f"status={status}")

    # ── 3. 归档接口 ──
    print("\n── 3. 归档接口 ──")

    status, body = request_json(f"{backend}/api/archive", timeout)
    if status == 200 and body:
        total = body.get("total", 0)
        items = body.get("items", [])
        stats.pass_(f"GET /api/archive (共 {total} 条)")

        if items:
            archive_id = items[0]["task_id"]
            status, body = request_json(f"{backend}/api/archive/{archive_id}", timeout)
            if status == 200 and body and body.get("meta"):
                stats.pass_(f"GET /api/archive/{archive_id}")
            else:
                stats.fail(f"GET /api/archive/{archive_id}", f"status={status}")
    else:
        stats.fail("GET /api/archive", f"status={status}")

    # ── 4. 设置接口 ──
    print("\n── 4. 设置接口 ──")

    # 先获取一个有效模型 ID
    status, models_body = request_json(f"{backend}/api/models", timeout)
    model_id = None
    if models_body and models_body.get("data"):
        model_id = models_body["data"][0]["id"]

    if model_id:
        status, body = request_json(
            f"{backend}/api/settings/default-model", timeout,
            method="PATCH", payload={"model_id": model_id},
        )
        if status == 200:
            stats.pass_(f"PATCH /api/settings/default-model → {model_id}")
        else:
            stats.fail("PATCH /api/settings/default-model", f"status={status}")
    else:
        stats.warning("PATCH /api/settings/default-model", "无法获取模型列表")

    # ── 5. 聊天接口 ──
    print("\n── 5. 聊天接口 ──")

    status, text = request_text(f"{backend}/api/chat/stream", timeout + 5, method="POST", payload={
        "messages": [{"role": "user", "content": "说一个字"}],
        "stream": True,
    })
    if status == 200 and "event:" in text:
        stats.pass_("POST /api/chat/stream (SSE)")
    else:
        stats.fail("POST /api/chat/stream", f"status={status}")

    status, body = request_json(f"{backend}/api/chat/completions", timeout + 10, method="POST", payload={
        "messages": [{"role": "user", "content": "说一个字"}],
        "stream": False,
    })
    if status == 200 and body and body.get("choices"):
        content = body["choices"][0].get("message", {}).get("content", "")
        stats.pass_(f"POST /api/chat/completions → {content[:20]}")
    else:
        stats.fail("POST /api/chat/completions", f"status={status}")

    # ── 6. 文件接口 ──
    print("\n── 6. 文件接口 ──")

    status, _ = request_text(f"{backend}/api/file-text?ref=/tasklog/invalid/path.txt", timeout)
    if status in (400, 404):
        stats.pass_("GET /api/file-text (无效ref → 400/404)")
    else:
        stats.warning("GET /api/file-text", f"status={status}（预期 400/404）")

    # ── 7. SPA 路由回退 ──
    print("\n── 7. SPA 路由回退 ──")

    spa_paths = [
        f"/tasks/fake-test-id/",
        f"/review/fake-test-id/",
        f"/result/fake-test-id/",
    ]
    for path in spa_paths:
        status, text = request_text(f"{backend}{path}", timeout)
        if status == 200 and "小说工坊" in text:
            stats.pass_(f"SPA fallback: {path} → index.html")
        elif status == 200:
            stats.warning(f"SPA fallback: {path}", "返回 200 但非 index.html 内容")
        else:
            stats.fail(f"SPA fallback: {path}", f"status={status}")

    # ── 8. CORS 检查 ──
    print("\n── 8. CORS 检查 ──")

    cors_origins = [
        "https://agentproject.pages.dev",
        "https://yuegui666.icu",
        "http://localhost:3000",
    ]
    for origin in cors_origins:
        req = urllib.request.Request(
            url=f"{backend}/api/health",
            method="OPTIONS",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                allow_origin = resp.headers.get("access-control-allow-origin", "")
                if allow_origin == origin:
                    stats.pass_(f"CORS: {origin} ✓")
                else:
                    stats.warning(f"CORS: {origin}", f"allow-origin={allow_origin}")
        except urllib.error.HTTPError as exc:
            stats.fail(f"CORS: {origin}", f"status={exc.code}")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    print(f"测试完成：✅ {stats.ok} 通过  ⚠️ {stats.warn} 警告  ❌ {stats.fail} 失败")
    print("=" * 60)

    return 1 if stats.fail > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
