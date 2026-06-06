import assert from "node:assert/strict";
import test from "node:test";

import { buildChapterProgress, buildThinkingGroups } from "./task-run-state.mjs";

test("buildChapterProgress 用 novel_progress 兜底显示已完成章节", () => {
  const items = buildChapterProgress([], {
    completed_chapter_count: 6,
    next_chapter_number: 7,
  });

  assert.equal(items.length, 6);
  assert.equal(items.at(-1).number, 6);
  assert.equal(items.at(-1).status, "已完成");
});

test("buildChapterProgress 对同章事件按时间取最新状态", () => {
  const items = buildChapterProgress([
    {
      event_id: "new",
      event_type: "chapter.saved",
      created_at: "2026-05-07T10:00:00Z",
      unit_id: "chapter-05",
      payload: { chapter_number: 5, chapter_title: "新版", chapter_summary: "已保存" },
    },
    {
      event_id: "old",
      event_type: "chapter.started",
      created_at: "2026-05-07T09:00:00Z",
      unit_id: "chapter-05",
      payload: { chapter_number: 5, chapter_title: "旧版" },
    },
  ]);

  assert.equal(items.length, 1);
  assert.equal(items[0].title, "新版");
  assert.equal(items[0].status, "已完成");
});

test("buildChapterProgress 在等待验证时仍保留已完成章节", () => {
  const items = buildChapterProgress(
    [
      {
        event_id: "saved",
        event_type: "chapter.saved",
        created_at: "2026-05-07T10:00:00Z",
        unit_id: "chapter-01",
        payload: { chapter_number: 1, chapter_title: "第一章", chapter_summary: "已完成正文" },
      },
    ],
    {
      status: "waiting_verification_review",
      completed_chapter_count: 1,
    },
  );

  assert.equal(items.length, 1);
  assert.equal(items[0].number, 1);
  assert.equal(items[0].title, "第一章");
  assert.equal(items[0].status, "已完成");
  assert.equal(items[0].progress, 100);
});

test("buildThinkingGroups 最新章节思考排在前面并标记活跃", () => {
  const groups = buildThinkingGroups(
    [
      {
        event_type: "model.thinking",
        created_at: "2026-05-07T09:00:00Z",
        stage: "drafting",
        unit_id: "chapter-04",
        payload: { reasoning_chunk: "旧" },
      },
      {
        event_type: "model.thinking",
        created_at: "2026-05-07T10:00:00Z",
        stage: "drafting",
        unit_id: "chapter-06",
        payload: { reasoning_chunk: "新" },
      },
    ],
    "drafting",
  );

  assert.equal(groups[0].unitId, "chapter-06");
  assert.equal(groups[0].isActive, true);
  assert.equal(groups[1].unitId, "chapter-04");
});

test("buildThinkingGroups 运行中按当前批次过滤旧章节思考", () => {
  const groups = buildThinkingGroups(
    [
      {
        event_type: "model.thinking",
        created_at: "2026-05-07T09:00:00Z",
        stage: "drafting",
        unit_id: "chapter-04",
        payload: { reasoning_chunk: "旧第 4 章" },
      },
      {
        event_type: "chapter.started",
        created_at: "2026-05-07T10:00:00Z",
        stage: "drafting",
        unit_id: "chapter-08",
        payload: { chapter_number: 8, chapter_title: "新第 8 章" },
      },
    ],
    "drafting",
    { minimumChapterNumber: 7 },
  );

  assert.equal(groups.length, 0);
});
