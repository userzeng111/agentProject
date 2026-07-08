function toTime(value) {
  const time = new Date(value || 0).getTime();
  return Number.isFinite(time) ? time : 0;
}

function resolveChapterNumber(event) {
  const value = event?.payload?.chapter_number;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed)) return parsed;
  }
  const match = String(event?.unit_id || "").match(/chapter-(\d+)/);
  return match ? Number.parseInt(match[1], 10) : null;
}

function toPositiveInteger(value) {
  const parsed = Number.parseInt(value ?? 0, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function latestEvent(events = []) {
  if (!Array.isArray(events) || events.length === 0) return null;
  return [...events].sort((left, right) => toTime(right.created_at) - toTime(left.created_at))[0] || null;
}

function statusTone(status) {
  if (status === "completed") return "success";
  if (status === "failed" || status === "cancelled") return "error";
  if (
    [
      "planning",
      "drafting",
      "assembling",
      "waiting_outline_review",
      "waiting_chapter_review",
      "waiting_verification_review",
      "waiting_manual_action",
    ].includes(status || "")
  ) {
    return "warning";
  }
  return "default";
}

function normalizeTerminalStatus(value = "") {
  const normalized = String(value || "").trim().replace(/^task\./, "");
  return ["completed", "cancelled", "failed"].includes(normalized) ? normalized : "";
}

export function resolveWorkspaceStageNav(status = "") {
  const stages = [
    { label: "创建", description: "素材与任务创建" },
    { label: "规划", description: "大纲与章节计划" },
    { label: "审核", description: "人工确认与修订" },
    { label: "创作", description: "正文生成与整理" },
    { label: "完成", description: "结果待确认" },
  ];
  const activeStepByStatus = {
    created: 0,
    sources_ingested: 0,
    planning: 1,
    waiting_outline_review: 1,
    waiting_chapter_review: 2,
    waiting_verification_review: 2,
    waiting_manual_action: 2,
    ready_for_batch: 3,
    drafting: 3,
    assembling: 3,
    completed: 4,
    failed: 2,
    cancelled: 2,
  };

  return { stages, activeStep: activeStepByStatus[status] ?? 0 };
}

export function resolveTerminalEventStreamState(statusOrEventType = "") {
  const status = normalizeTerminalStatus(statusOrEventType);
  if (status === "completed") return "任务已完成，事件流已关闭";
  if (status === "cancelled") return "任务已取消，事件流已关闭";
  if (status === "failed") return "任务失败，事件流已关闭";
  return "";
}

export function resolveEventStreamErrorTransition({
  opened = false,
  terminalEventReceived = false,
  reconnectAttempts = 0,
  maxReconnect = 3,
  reconnectDelaySeconds = 2,
  terminalState = "",
} = {}) {
  if (terminalEventReceived) {
    return {
      action: "terminal",
      nextReconnectAttempts: reconnectAttempts,
      streamState: terminalState || "任务已结束，事件流已关闭",
    };
  }
  if (!opened) {
    return {
      action: "next_path",
      nextReconnectAttempts: reconnectAttempts,
      streamState: "",
    };
  }
  if (reconnectAttempts < maxReconnect) {
    const nextReconnectAttempts = reconnectAttempts + 1;
    return {
      action: "reconnect",
      nextReconnectAttempts,
      streamState: `事件流已断开，${reconnectDelaySeconds}秒后第${nextReconnectAttempts}次重连...`,
    };
  }
  return {
    action: "manual",
    nextReconnectAttempts: reconnectAttempts,
    streamState: "事件流已断开，当前使用手动刷新",
  };
}

function isAfterMainStage(activeId, stageId) {
  const order = ["prepare", "outline", "chapter-plan", "drafting", "verification", "assembly"];
  return order.indexOf(stageId) < order.indexOf(activeId);
}

function resolveActiveMainStage(workspace = {}) {
  const status = workspace?.meta?.status || "";
  const currentStage = workspace?.meta?.current_stage || "";
  const currentUnit = workspace?.meta?.current_unit || "";
  const outlinePhase = workspace?.outline_phase || "";

  if (status === "completed" || currentStage === "completed") return "assembly";
  if (status === "assembling") return "assembly";
  if (
    status === "waiting_verification_review" ||
    currentStage === "verification" ||
    currentStage === "waiting_verification_review" ||
    currentUnit === "verification"
  ) {
    return "verification";
  }
  if (["drafting", "waiting_chapter_review", "ready_for_batch"].includes(status)) return "drafting";
  if (status === "waiting_outline_review" && outlinePhase === "chapter_batches") return "chapter-plan";
  if (["planning", "waiting_outline_review"].includes(status)) return "outline";
  if (status === "failed" || status === "cancelled" || status === "waiting_manual_action") {
    if (currentStage === "verification" || currentUnit === "verification") return "verification";
    if (currentStage === "drafting" || currentStage === "waiting_chapter_review") return "drafting";
    if (currentStage === "waiting_outline_review" && outlinePhase === "chapter_batches") return "chapter-plan";
    if (currentStage === "planning" || currentStage === "waiting_outline_review") return "outline";
  }
  return "prepare";
}

function stageState(workspace, stageId, activeId) {
  const status = workspace?.meta?.status || "";
  if ((status === "failed" || status === "cancelled") && stageId === activeId) return "error";
  if (stageId === activeId) return "active";
  if (isAfterMainStage(activeId, stageId)) return "done";
  return "pending";
}

function stepState(isDone, isActive, isError = false) {
  if (isError) return "error";
  if (isActive) return "active";
  return isDone ? "done" : "pending";
}

function buildOutlineSection(workspace, activeId) {
  const status = workspace?.meta?.status || "";
  const outlinePhase = workspace?.outline_phase || "";
  const completed = toPositiveInteger(workspace?.outline_completed_count);
  const total = toPositiveInteger(workspace?.outline_total_count);
  const isError = (status === "failed" || status === "cancelled") && ["outline", "chapter-plan"].includes(activeId);
  const outlineDone = isAfterMainStage(activeId, "outline") || isAfterMainStage(activeId, "chapter-plan");
  const isOutlineActive = activeId === "outline";
  const isChapterPlanActive = activeId === "chapter-plan";

  return {
    id: "outline",
    title: "大纲与章节计划",
    state: isError ? "error" : isOutlineActive || isChapterPlanActive ? "active" : outlineDone ? "done" : "pending",
    targetTab: 0,
    metrics: [
      { label: "已确认章节", value: total > 0 ? `${completed} / ${total}` : "未开始" },
      { label: "大纲阶段", value: outlinePhase === "chapter_batches" ? "章节计划" : "总纲" },
    ],
    steps: [
      { id: "prepare-outline-context", label: "整理素材上下文", state: stepState(outlineDone || isOutlineActive || isChapterPlanActive, false) },
      {
        id: "plan-story",
        label: "生成总纲",
        state: stepState(outlineDone || isChapterPlanActive || status === "waiting_outline_review", status === "planning" && isOutlineActive, isError && isOutlineActive),
      },
      {
        id: "outline-review",
        label: "审核总纲",
        state: stepState(outlineDone || isChapterPlanActive, status === "waiting_outline_review" && outlinePhase !== "chapter_batches", isError && isOutlineActive),
      },
      {
        id: "chapter-batch-review",
        label: "章节计划批次",
        state: stepState(outlineDone, isChapterPlanActive, isError && isChapterPlanActive),
      },
    ],
  };
}

function buildDraftingSection(workspace, activeId) {
  const status = workspace?.meta?.status || "";
  const progress = workspace?.novel_progress || {};
  const planned = toPositiveInteger(progress.planned_chapter_count || progress.target_chapter_count);
  const completed = toPositiveInteger(progress.completed_chapter_count);
  const generating = toPositiveInteger(progress.current_generating_chapter_number);
  const nextChapter = toPositiveInteger(progress.next_chapter_number);
  const isActive = activeId === "drafting";
  const isDone = isAfterMainStage(activeId, "drafting") || status === "completed";
  const isError = (status === "failed" || status === "cancelled") && isActive;

  return {
    id: "drafting",
    title: "正文生成与章节审核",
    state: isError ? "error" : isActive ? "active" : isDone ? "done" : "pending",
    targetTab: 1,
    metrics: [
      { label: "已完成章节", value: planned > 0 ? `${completed} / ${planned}` : `${completed}` },
      { label: "当前章节", value: generating || nextChapter || "未开始" },
    ],
    steps: [
      { id: "prepare-chapter-context", label: "准备章节上下文", state: stepState(isDone || isActive, false) },
      {
        id: "draft-chapters",
        label: "生成章节对",
        state: stepState(isDone || ["waiting_chapter_review", "ready_for_batch"].includes(status), status === "drafting" && isActive, isError && isActive),
      },
      {
        id: "chapter-review",
        label: "章节门禁与审核",
        state: stepState(isDone || status === "ready_for_batch", status === "waiting_chapter_review", isError && isActive),
      },
      {
        id: "accumulate-chapters",
        label: "累计章节 / 等待继续",
        state: stepState(isDone, status === "ready_for_batch", false),
      },
    ],
  };
}

function buildVerificationSection(workspace, activeId) {
  const status = workspace?.meta?.status || "";
  const currentStage = workspace?.meta?.current_stage || "";
  const isActive = activeId === "verification";
  const isAssembly = activeId === "assembly";
  const isDone = status === "completed";
  const isError = (status === "failed" || status === "cancelled") && isActive;

  return {
    id: "verification",
    title: "全文验证与修复",
    state: isError ? "error" : isActive || isAssembly ? "active" : isDone ? "done" : "pending",
    targetTab: 0,
    metrics: [
      { label: "验证状态", value: status === "waiting_verification_review" ? "待审核" : isDone ? "已完成" : isActive ? "进行中" : "未开始" },
      { label: "结果整理", value: status === "assembling" ? "进行中" : status === "completed" ? "已完成" : "待处理" },
    ],
    steps: [
      {
        id: "verify-story",
        label: "全文验证",
        state: stepState(isAssembly || isDone || status === "waiting_verification_review", isActive && status !== "waiting_verification_review" && !isError, false),
      },
      {
        id: "verification-review",
        label: "验证审核",
        state: stepState(isAssembly || isDone, status === "waiting_verification_review", false),
      },
      {
        id: "fix-issues",
        label: "问题修复",
        state: stepState(isAssembly || isDone, isError || (isActive && currentStage === "verification" && status !== "waiting_verification_review"), false),
      },
      {
        id: "assemble-result",
        label: "结果整理",
        state: stepState(isDone, status === "assembling" || status === "completed", false),
      },
    ],
  };
}

function graphStateFromWorkflowState(state) {
  if (state === "error") return "error";
  if (state === "active") return "active";
  if (state === "done") return "done";
  return "pending";
}

function workflowNode(id, label, x, y, state, detail = "") {
  return {
    id: `workflow-${id}`,
    type: "statusNode",
    position: { x, y },
    data: {
      label,
      detail,
      kind: "workflow",
      state: graphStateFromWorkflowState(state),
    },
  };
}

function workflowEdge(source, target, state = "pending", label = "") {
  return {
    id: `workflow-${source}-${target}`,
    source: `workflow-${source}`,
    target: `workflow-${target}`,
    type: "smoothstep",
    animated: state === "active",
    label,
    data: { state },
  };
}

export function buildWorkflowGraph(workspace = {}) {
  const overview = buildWorkflowOverview(workspace);
  const stagesById = new Map(overview.mainStages.map((stage) => [stage.id, stage]));
  const status = workspace?.meta?.status || "";
  const progress = workspace?.novel_progress || {};
  const completed = toPositiveInteger(progress.completed_chapter_count);
  const planned = toPositiveInteger(progress.planned_chapter_count || progress.target_chapter_count);
  const currentChapter = toPositiveInteger(progress.current_generating_chapter_number || progress.next_chapter_number);
  const outlineDone = toPositiveInteger(workspace?.outline_completed_count);
  const outlineTotal = toPositiveInteger(workspace?.outline_total_count);

  const nodeSpecs = [
    ["prepare", "任务准备", 0, 80, `进度 ${overview.progress}%`],
    ["outline", "大纲规划", 220, 80, overview.currentStage || "等待启动"],
    ["chapter-plan", "章节计划", 440, 80, outlineTotal > 0 ? `${outlineDone}/${outlineTotal} 章` : "待生成"],
    ["drafting", "正文生成", 660, 20, currentChapter ? `当前第 ${currentChapter} 章` : "待生成"],
    ["chapter-review", "章节审核", 660, 150, status === "waiting_chapter_review" ? "待审核" : "自动/人工门禁"],
    ["verification", "全文验证", 900, 80, "一致性与修复"],
    ["assembly", "结果整理", 1120, 80, planned > 0 ? `${completed}/${planned} 章` : "结果输出"],
  ];

  const activeStageId = overview.activeMainStageId;
  const chapterReviewActive = status === "waiting_chapter_review";
  const nodes = nodeSpecs.map(([id, label, x, y, detail]) => {
    let state = stagesById.get(id)?.state || "pending";
    if (id === "chapter-review") {
      state = chapterReviewActive ? "active" : activeStageId === "drafting" && completed > 0 ? "done" : "pending";
    }
    if (id === "drafting" && chapterReviewActive) {
      state = "done";
    }
    return workflowNode(id, label, x, y, state, detail);
  });

  const edges = [
    workflowEdge("prepare", "outline", stagesById.get("prepare")?.state === "done" ? "done" : "pending"),
    workflowEdge("outline", "chapter-plan", stagesById.get("outline")?.state === "done" ? "done" : "pending"),
    workflowEdge("chapter-plan", "drafting", stagesById.get("chapter-plan")?.state === "done" ? "done" : "pending"),
    workflowEdge("drafting", "chapter-review", chapterReviewActive ? "active" : completed > 0 ? "done" : "pending"),
    workflowEdge("chapter-review", "drafting", status === "drafting" ? "active" : "pending", "继续下一批"),
    workflowEdge("chapter-review", "verification", activeStageId === "verification" || activeStageId === "assembly" ? "done" : "pending"),
    workflowEdge("verification", "assembly", activeStageId === "assembly" ? "active" : status === "completed" ? "done" : "pending"),
  ];

  return {
    nodes,
    edges,
    summary: {
      activeMainStageId: activeStageId,
      currentStage: overview.currentStage,
      currentUnit: overview.currentUnit,
      progress: overview.progress,
      message: overview.summary,
    },
  };
}

function traceState(status) {
  if (status === "failed") return "error";
  if (status === "running") return "active";
  if (status === "completed") return "done";
  return "pending";
}

function traceKind(agent) {
  if (
    agent?.execution_kind === "main_agent" ||
    agent?.execution_kind === "subagent" ||
    agent?.execution_kind === "synthesis"
  ) {
    return agent.execution_kind;
  }
  if (agent?.role === "orchestrator") return "main_agent";
  if (agent?.role === "synthesis") return "synthesis";
  return "subagent";
}

function isTraceSummary(item) {
  return Boolean(item && item.__summary__);
}

function currentTraceRoundItems(trace = []) {
  const items = Array.isArray(trace) ? trace : [];
  let lastSummaryIndex = -1;
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (isTraceSummary(items[index])) {
      lastSummaryIndex = index;
      break;
    }
  }
  if (lastSummaryIndex < 0) {
    return { summary: null, agents: items.filter(Boolean) };
  }
  return {
    summary: items[lastSummaryIndex],
    agents: items.slice(lastSummaryIndex + 1).filter(Boolean),
  };
}

function agentNode(agent, index, x, y) {
  const kind = traceKind(agent);
  return {
    id: `agent-${agent.agent_id || `${kind}-${index}`}`,
    type: "statusNode",
    position: { x, y },
    data: {
      label: agent.agent_name || agent.role || "未命名 Agent",
      detail: agent.error || agent.reasoning || agent.role || "",
      kind,
      state: traceState(agent.status),
      score: typeof agent.score === "number" ? Math.round(agent.score) : undefined,
      issueCount: Array.isArray(agent.issues) ? agent.issues.length : 0,
      warningCount: Array.isArray(agent.warnings) ? agent.warnings.length : 0,
      role: agent.role || "",
      invocationKind: agent.invocation_kind || "",
    },
  };
}

export function buildAgentDispatchGraph(trace = []) {
  const { summary, agents } = currentTraceRoundItems(trace);
  if (!agents.length) {
    return {
      nodes: [],
      edges: [],
      summary: {
        score: typeof summary?.overall_score === "number" ? Math.round(summary.overall_score) : 0,
        completedCount: 0,
        failedCount: 0,
        agentCount: 0,
        traceRound: summary?.trace_round || 0,
        reviewType: summary?.review_type || "",
      },
    };
  }

  const mainAgents = agents.filter((agent) => traceKind(agent) === "main_agent");
  const subAgents = agents.filter((agent) => traceKind(agent) === "subagent");
  const synthesisAgents = agents.filter((agent) => traceKind(agent) === "synthesis");
  const fallbackMain = mainAgents[0] || agents[0];
  const mainId = fallbackMain?.agent_id || "main";

  const nodes = [];
  if (fallbackMain) {
    nodes.push(agentNode(fallbackMain, 0, 0, Math.max(0, (subAgents.length - 1) * 70)));
  }

  subAgents.forEach((agent, index) => {
    nodes.push(agentNode(agent, index + 1, 300, index * 140));
  });

  synthesisAgents.forEach((agent, index) => {
    nodes.push(agentNode(agent, index + 1 + subAgents.length, 640, Math.max(0, (subAgents.length - 1) * 70) + index * 120));
  });

  const edges = [];
  for (const agent of subAgents) {
    const source = `agent-${agent.parent_agent_id || mainId}`;
    const target = `agent-${agent.agent_id}`;
    edges.push({
      id: `${source}-${target}`,
      source,
      target,
      type: "smoothstep",
      animated: agent.status === "running",
      data: { state: traceState(agent.status) },
    });
  }

  for (const synthesis of synthesisAgents) {
    const target = `agent-${synthesis.agent_id}`;
    const upstream = subAgents.length ? subAgents : [fallbackMain].filter(Boolean);
    for (const agent of upstream) {
      const source = `agent-${agent.agent_id || mainId}`;
      edges.push({
        id: `${source}-${target}`,
        source,
        target,
        type: "smoothstep",
        animated: synthesis.status === "running",
        data: { state: traceState(synthesis.status) },
      });
    }
  }

  const trackedAgents = agents.filter((agent) => traceKind(agent) !== "main_agent");
  const completedAgents = trackedAgents.filter((agent) => agent.status === "completed");
  const failedCount = trackedAgents.filter((agent) => agent.status === "failed").length;
  const score = typeof summary?.overall_score === "number"
    ? Math.round(summary.overall_score)
    : completedAgents.length
      ? Math.round(completedAgents.reduce((total, agent) => total + (agent.score || 0), 0) / completedAgents.length)
      : 0;

  return {
    nodes,
    edges,
    summary: {
      score,
      completedCount: completedAgents.length,
      failedCount,
      agentCount: trackedAgents.length,
      traceRound: summary?.trace_round || 0,
      reviewType: summary?.review_type || "",
    },
  };
}

export function buildWorkflowOverview(workspace = {}) {
  const status = workspace?.meta?.status || "created";
  const activeMainStageId = resolveActiveMainStage(workspace);
  const event = latestEvent(workspace?.recent_events);
  const mainStageSpecs = [
    { id: "prepare", label: "任务准备", targetTab: 3 },
    { id: "outline", label: "大纲规划", targetTab: 0 },
    { id: "chapter-plan", label: "章节计划", targetTab: 0 },
    { id: "drafting", label: "正文创作", targetTab: 1 },
    { id: "verification", label: "全文验证", targetTab: 0 },
    { id: "assembly", label: "结果整理", targetTab: 3 },
  ];

  return {
    activeMainStageId,
    defaultExpandedSectionId: activeMainStageId === "chapter-plan" || activeMainStageId === "outline"
      ? "outline"
      : activeMainStageId === "drafting"
        ? "drafting"
        : activeMainStageId === "verification" || activeMainStageId === "assembly"
          ? "verification"
          : "outline",
    statusTone: statusTone(status),
    progress: Number.parseInt(workspace?.meta?.progress ?? 0, 10) || 0,
    currentStage: workspace?.meta?.current_stage || "",
    currentUnit: workspace?.meta?.current_unit || "",
    summary: event?.message || workspace?.meta?.summary || "暂无过程信息",
    mainStages: mainStageSpecs.map((stage) => ({
      ...stage,
      state: stageState(workspace, stage.id, activeMainStageId),
    })),
    sections: [
      buildOutlineSection(workspace, activeMainStageId),
      buildDraftingSection(workspace, activeMainStageId),
      buildVerificationSection(workspace, activeMainStageId),
    ],
  };
}

export function buildChapterProgress(events = [], novelProgress = {}) {
  const chapterMap = new Map();

  for (const event of events.filter((item) => String(item?.event_type || "").startsWith("chapter."))) {
    const chapterNumber = resolveChapterNumber(event);
    if (typeof chapterNumber !== "number" || chapterNumber <= 0) continue;
    const current = chapterMap.get(chapterNumber);
    if (current && toTime(event.created_at) < toTime(current.updatedAt)) continue;
    const title = event.payload?.chapter_title || current?.title || event.unit_id || `第 ${chapterNumber} 章`;
    chapterMap.set(chapterNumber, {
      number: chapterNumber,
      title,
      status: event.event_type === "chapter.saved" ? "已完成" : "生成中",
      progress: event.event_type === "chapter.saved" ? 100 : 56,
      summary: event.payload?.chapter_summary || current?.summary,
      updatedAt: event.created_at,
    });
  }

  const completedCount = Number.parseInt(novelProgress?.completed_chapter_count ?? 0, 10);
  if (Number.isFinite(completedCount) && completedCount > 0) {
    for (let number = 1; number <= completedCount; number += 1) {
      const current = chapterMap.get(number);
      chapterMap.set(number, {
        number,
        title: current?.title || `第 ${number} 章`,
        status: "已完成",
        progress: 100,
        summary: current?.summary,
        updatedAt: current?.updatedAt || "",
      });
    }
  }

  const generatingNumber = Number.parseInt(novelProgress?.current_generating_chapter_number ?? 0, 10);
  if (Number.isFinite(generatingNumber) && generatingNumber > 0) {
    const current = chapterMap.get(generatingNumber);
    chapterMap.set(generatingNumber, {
      number: generatingNumber,
      title: current?.title || `第 ${generatingNumber} 章`,
      status: "生成中",
      progress: Math.max(current?.progress || 0, 56),
      summary: current?.summary,
      updatedAt: current?.updatedAt || "",
    });
  }

  return Array.from(chapterMap.values()).sort((left, right) => left.number - right.number);
}

export function buildThinkingGroups(events = [], workspaceStatus, options = {}) {
  const minimumChapterNumber = toPositiveInteger(options?.minimumChapterNumber);
  const isTaskRunning = ["planning", "drafting", "assembling", "verification"].includes(workspaceStatus || "");
  const thinkingEvents = events.filter((event) => {
    if (event?.event_type !== "model.thinking") return false;
    const chapterNumber = resolveChapterNumber(event);
    if (isTaskRunning && minimumChapterNumber > 0 && chapterNumber !== null) {
      return chapterNumber >= minimumChapterNumber;
    }
    return true;
  });
  if (!thinkingEvents.length) return [];

  const groupMap = new Map();
  for (const event of thinkingEvents) {
    const key = event.unit_id || "default";
    const existing = groupMap.get(key);
    const chunk = event.payload?.reasoning_chunk || "";
    const model = event.payload?.model || existing?.model || "";
    const finishReason = event.payload?.finish_reason ?? existing?.finishReason ?? null;
    groupMap.set(key, {
      unitId: key,
      stage: event.stage || "",
      content: (existing?.content || "") + chunk,
      lastUpdatedAt: event.created_at,
      isActive: false,
      model,
      finishReason,
    });
  }

  const groups = Array.from(groupMap.values()).sort((left, right) => toTime(right.lastUpdatedAt) - toTime(left.lastUpdatedAt));
  if (isTaskRunning && groups.length > 0) {
    groups[0].isActive = true;
  }

  return groups;
}
