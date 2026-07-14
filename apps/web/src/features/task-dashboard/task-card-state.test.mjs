import assert from "node:assert/strict";
import test from "node:test";

import { resolveTaskHref } from "./task-card-state.mjs";

test("已完成任务即使已归档也优先进入结果页", () => {
  assert.equal(
    resolveTaskHref({ task_id: "task_done", status: "completed", storage_state: "archive" }),
    "/p/task_done/?view=result",
  );
});

test("非完成归档任务仍进入归档视图", () => {
  assert.equal(
    resolveTaskHref({ task_id: "task_failed", status: "failed", storage_state: "archive" }),
    "/p/task_failed/?view=archive",
  );
});

test("待审核任务进入审核视图", () => {
  assert.equal(
    resolveTaskHref({ task_id: "task_review", status: "waiting_chapter_review", storage_state: "runs" }),
    "/p/task_review/?view=review",
  );
});

test("普通任务进入项目工作台新路由", () => {
  assert.equal(
    resolveTaskHref({ task_id: "task_active", status: "running", storage_state: "runs" }),
    "/p/task_active/",
  );
});
