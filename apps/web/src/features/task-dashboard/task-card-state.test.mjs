import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeLibraryTab,
  resolveLibraryTabIndex,
  resolveLibraryReturnHref,
  resolveLibraryTabValue,
  resolveTaskHref,
} from "./task-card-state.mjs";

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

test("进入项目时保留作品库来源分类", () => {
  assert.equal(
    resolveTaskHref({ task_id: "task_failed", status: "failed", storage_state: "runs" }, "failed"),
    "/p/task_failed/?library_tab=failed",
  );
  assert.equal(
    resolveTaskHref({ task_id: "task_done", status: "completed", storage_state: "runs" }, "completed"),
    "/p/task_done/?view=result&library_tab=completed",
  );
});

test("作品库来源分类仅接受白名单并可映射到标签索引", () => {
  assert.equal(normalizeLibraryTab("failed"), "failed");
  assert.equal(normalizeLibraryTab("unexpected"), null);
  assert.equal(resolveLibraryTabIndex("failed"), 2);
  assert.equal(resolveLibraryTabIndex("unexpected"), 0);
  assert.equal(resolveLibraryTabValue(3), "completed");
  assert.equal(resolveLibraryTabValue(99), "pending");
  assert.equal(resolveLibraryReturnHref("failed"), "/?library_tab=failed");
  assert.equal(resolveLibraryReturnHref("unexpected"), "/");
});
