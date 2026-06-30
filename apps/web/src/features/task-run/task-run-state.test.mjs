import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentDispatchGraph,
  buildChapterProgress,
  buildThinkingGroups,
  buildWorkflowGraph,
  buildWorkflowOverview,
  resolveEventStreamErrorTransition,
  resolveTerminalEventStreamState,
  resolveWorkspaceStageNav,
} from "./task-run-state.mjs";

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

test("resolveWorkspaceStageNav 把工作台状态映射到项目阶段导航", () => {
  const nav = resolveWorkspaceStageNav("created");

  assert.equal(nav.stages.length, 5);
  assert.deepEqual(
    nav.stages.map((stage) => stage.label),
    ["创建", "规划", "审核", "创作", "完成"],
  );

  for (const status of ["created", "sources_ingested"]) {
    assert.equal(resolveWorkspaceStageNav(status).activeStep, 0, status);
  }
  for (const status of ["planning", "waiting_outline_review"]) {
    assert.equal(resolveWorkspaceStageNav(status).activeStep, 1, status);
  }
  for (const status of ["waiting_chapter_review", "waiting_verification_review", "waiting_manual_action"]) {
    assert.equal(resolveWorkspaceStageNav(status).activeStep, 2, status);
  }
  for (const status of ["ready_for_batch", "drafting", "assembling"]) {
    assert.equal(resolveWorkspaceStageNav(status).activeStep, 3, status);
  }
  assert.equal(resolveWorkspaceStageNav("completed").activeStep, 4);
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

test("buildWorkflowOverview 标记章节计划批次阶段并默认展开大纲子流程", () => {
  const overview = buildWorkflowOverview({
    meta: {
      status: "waiting_outline_review",
      current_stage: "waiting_outline_review",
      current_unit: "outline",
      progress: 55,
    },
    outline_phase: "chapter_batches",
    outline_completed_count: 20,
    outline_total_count: 80,
    recent_events: [
      {
        event_type: "review.waiting",
        stage: "waiting_outline_review",
        message: "章节计划批次等待审核。",
        created_at: "2026-06-11T10:00:00Z",
      },
    ],
  });

  assert.equal(overview.activeMainStageId, "chapter-plan");
  assert.equal(overview.defaultExpandedSectionId, "outline");
  assert.equal(overview.summary, "章节计划批次等待审核。");
  assert.equal(overview.sections[0].metrics[0].value, "20 / 80");
  assert.equal(overview.sections[0].steps.find((item) => item.id === "chapter-batch-review").state, "active");
});

test("buildWorkflowOverview 标记正文创作循环并把主阶段联动到章节 Tab", () => {
  const overview = buildWorkflowOverview({
    meta: {
      status: "drafting",
      current_stage: "drafting",
      current_unit: "chapter-pair-3",
      progress: 68,
    },
    novel_progress: {
      planned_chapter_count: 8,
      completed_chapter_count: 4,
      next_chapter_number: 5,
      current_generating_chapter_number: 5,
    },
    recent_events: [
      {
        event_type: "chapter.started",
        stage: "drafting",
        unit_id: "chapter-05",
        message: "开始生成第 5 章。",
        created_at: "2026-06-11T10:00:00Z",
        payload: { chapter_number: 5 },
      },
    ],
  });

  assert.equal(overview.activeMainStageId, "drafting");
  assert.equal(overview.defaultExpandedSectionId, "drafting");
  assert.equal(overview.mainStages.find((item) => item.id === "drafting").targetTab, 1);
  assert.equal(overview.sections[1].metrics[0].value, "4 / 8");
  assert.equal(overview.sections[1].steps.find((item) => item.id === "draft-chapters").state, "active");
});

test("buildWorkflowOverview 标记验证修复循环和失败状态", () => {
  const overview = buildWorkflowOverview({
    meta: {
      status: "failed",
      current_stage: "verification",
      current_unit: "verification",
      progress: 92,
    },
    recent_events: [
      {
        event_type: "task.failed",
        stage: "verification",
        unit_id: "verification",
        message: "全文验证修复失败。",
        created_at: "2026-06-11T10:00:00Z",
      },
    ],
  });

  assert.equal(overview.activeMainStageId, "verification");
  assert.equal(overview.statusTone, "error");
  assert.equal(overview.defaultExpandedSectionId, "verification");
  assert.equal(overview.sections[2].steps.find((item) => item.id === "fix-issues").state, "active");
});

test("buildWorkflowGraph 生成主流程节点并高亮当前正文阶段", () => {
  const graph = buildWorkflowGraph({
    meta: {
      status: "waiting_chapter_review",
      current_stage: "waiting_chapter_review",
      current_unit: "chapter-pair-2",
      progress: 74,
    },
    novel_progress: {
      completed_chapter_count: 4,
      planned_chapter_count: 8,
      current_generating_chapter_number: 5,
    },
    recent_events: [],
  });

  assert.equal(graph.nodes.length >= 7, true);
  assert.equal(graph.edges.some((edge) => edge.source === "workflow-drafting" && edge.target === "workflow-chapter-review"), true);
  assert.equal(graph.nodes.find((node) => node.id === "workflow-chapter-review").data.state, "active");
  assert.equal(graph.nodes.find((node) => node.id === "workflow-drafting").data.state, "done");
});

test("buildAgentDispatchGraph 将审核 trace 转成主从派发 DAG", () => {
  const graph = buildAgentDispatchGraph([
    {
      __summary__: true,
      trace_round: 2,
      review_type: "chapter_pair_review",
      overall_score: 78,
    },
    {
      agent_id: "main",
      agent_name: "主审核编排 Agent",
      role: "orchestrator",
      execution_kind: "main_agent",
      status: "completed",
      score: 78,
    },
    {
      agent_id: "structure",
      agent_name: "结构分析 Agent",
      role: "structure",
      execution_kind: "subagent",
      parent_agent_id: "main",
      status: "completed",
      score: 82,
    },
    {
      agent_id: "quality",
      agent_name: "质量审校 Agent",
      role: "quality",
      execution_kind: "subagent",
      parent_agent_id: "main",
      status: "failed",
      score: 0,
      error: "模型返回异常",
    },
    {
      agent_id: "synthesis",
      agent_name: "综合裁决 Agent",
      role: "synthesis",
      execution_kind: "synthesis",
      parent_agent_id: "main",
      status: "completed",
      score: 78,
    },
  ]);

  assert.equal(graph.nodes.length, 4);
  assert.equal(graph.edges.some((edge) => edge.source === "agent-main" && edge.target === "agent-structure"), true);
  assert.equal(graph.edges.some((edge) => edge.source === "agent-quality" && edge.target === "agent-synthesis"), true);
  assert.equal(graph.nodes.find((node) => node.id === "agent-quality").data.state, "error");
  assert.equal(graph.summary.failedCount, 1);
  assert.equal(graph.summary.score, 78);
});

test("resolveTerminalEventStreamState 为终态任务生成关闭文案", () => {
  assert.equal(resolveTerminalEventStreamState("completed"), "任务已完成，事件流已关闭");
  assert.equal(resolveTerminalEventStreamState("task.cancelled"), "任务已取消，事件流已关闭");
  assert.equal(resolveTerminalEventStreamState("task.failed"), "任务失败，事件流已关闭");
});

test("resolveEventStreamErrorTransition 收到 task.done 后不再重连", () => {
  const transition = resolveEventStreamErrorTransition({
    opened: true,
    terminalEventReceived: true,
    reconnectAttempts: 0,
    maxReconnect: 3,
    reconnectDelaySeconds: 2,
    terminalState: "任务已完成，事件流已关闭",
  });

  assert.equal(transition.action, "terminal");
  assert.equal(transition.nextReconnectAttempts, 0);
  assert.equal(transition.streamState, "任务已完成，事件流已关闭");
});

test("resolveEventStreamErrorTransition 对非终态断开仍按次数重连", () => {
  const transition = resolveEventStreamErrorTransition({
    opened: true,
    terminalEventReceived: false,
    reconnectAttempts: 0,
    maxReconnect: 3,
    reconnectDelaySeconds: 2,
  });

  assert.equal(transition.action, "reconnect");
  assert.equal(transition.nextReconnectAttempts, 1);
  assert.equal(transition.streamState, "事件流已断开，2秒后第1次重连...");
});
