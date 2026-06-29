import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import ts from "typescript";

async function loadApiModule() {
  const sourcePath = fileURLToPath(new URL("./api.ts", import.meta.url));
  const streamEventsUrl = pathToFileURL(fileURLToPath(new URL("./stream-chat-events.mjs", import.meta.url))).href;
  let source = await readFile(sourcePath, "utf8");

  source = source
    .replace(/import\s*{[\s\S]*?}\s*from\s*"@\/lib\/types";\n/, "")
    .replace(/import\s*{ ChatStreamChunk, ChatDoneEvent }\s*from\s*"@\/lib\/types";\n/, "")
    .replace('from "@/lib/stream-chat-events.mjs"', `from "${streamEventsUrl}"`);

  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: sourcePath,
  }).outputText;

  const tempDir = await mkdtemp(path.join(os.tmpdir(), "api-test-"));
  const tempModulePath = path.join(tempDir, "api.mjs");
  await writeFile(tempModulePath, compiled, "utf8");

  try {
    return await import(`${pathToFileURL(tempModulePath).href}?ts=${Date.now()}`);
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
}

function withMockedConsole(run) {
  const originalInfo = console.info;
  const originalWarn = console.warn;
  const originalError = console.error;
  const info = [];
  const warn = [];
  const error = [];

  console.info = (...args) => info.push(args);
  console.warn = (...args) => warn.push(args);
  console.error = (...args) => error.push(args);

  return Promise.resolve()
    .then(() => run({ info, warn, error }))
    .finally(() => {
      console.info = originalInfo;
      console.warn = originalWarn;
      console.error = originalError;
    });
}

function withMockedDateNow(sequence, run) {
  const originalNow = Date.now;
  Date.now = () => sequence.shift() ?? originalNow();
  return Promise.resolve()
    .then(run)
    .finally(() => {
      Date.now = originalNow;
    });
}

test("统一请求入口输出开始和结束结构化日志，并记录 request_id", async () => {
  const api = await loadApiModule();
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async () =>
    new Response(JSON.stringify({ task_id: "task-1" }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": "req-123",
      },
    });

  try {
    await withMockedConsole(async ({ info }) => {
      await withMockedDateNow([1000, 1123], async () => {
        await api.getTask("task-1");
      });

      assert.equal(info.length, 2);
      assert.equal(info[0][0], "http.request.start");
      assert.deepEqual(info[0][1], {
        method: "GET",
        path: "/api/tasks/task-1",
      });
      assert.equal(info[1][0], "http.request.end");
      assert.deepEqual(info[1][1], {
        method: "GET",
        path: "/api/tasks/task-1",
        http_status: 200,
        request_id: "req-123",
        client_duration_ms: 123,
      });
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("continue 请求可把 continue_request_id 透传到结构化日志上下文", async () => {
  const api = await loadApiModule();
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async () =>
    new Response(JSON.stringify({ task_id: "task-2" }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": "req-continue-1",
      },
    });

  try {
    await withMockedConsole(async ({ info }) => {
      await withMockedDateNow([2000, 2099], async () => {
        await api.continueTask(
          "task-2",
          {
            requested_chapter_count: 2,
            continue_request_id: "continue-abc",
            model_id: "model-1",
          },
          {
            continue_request_id: "continue-abc",
          },
        );
      });

      assert.equal(info.length, 2);
      assert.equal(info[1][0], "http.request.end");
      assert.equal(info[1][1].continue_request_id, "continue-abc");
      assert.equal(info[1][1].request_id, "req-continue-1");
      assert.equal(info[1][1].path, "/api/tasks/task-2/continue");
      assert.equal(info[1][1].method, "POST");
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("API 客户端不再暴露历史无调用导出", async () => {
  const api = await loadApiModule();

  assert.equal(Object.hasOwn(api, "getModels"), false);
  assert.equal(Object.hasOwn(api, "getSupervisor"), false);
  assert.equal(Object.hasOwn(api, "fetchJsonRef"), false);
});
