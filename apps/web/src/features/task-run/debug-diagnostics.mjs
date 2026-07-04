import {
  getCurrentTraceRound,
  summarizeTraceRound,
} from "../task-review/trace-rounds.mjs";

const TERMINAL_STATUSES = new Set(["completed", "cancelled", "failed"]);
const WAITING_REVIEW_STATUSES = new Set([
  "waiting_outline_review",
  "waiting_chapter_review",
  "waiting_verification_review",
]);
const WAITING_USER_STATUSES = new Set([
  "created",
  "sources_ingested",
  "waiting_outline_review",
  "waiting_chapter_review",
  "waiting_verification_review",
  "waiting_manual_action",
  "ready_for_batch",
]);
const RUNNING_STATUSES = new Set([
  "planning",
  "drafting",
  "assembling",
]);

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(asObject(object), key);
}

function toInteger(value, fallback = 0) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return fallback;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toNumber(value, fallback = 0) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function latestEvent(events = []) {
  return asArray(events)
    .filter(Boolean)
    .sort((left, right) => {
      const rightTime = new Date(right.created_at || 0).getTime();
      const leftTime = new Date(left.created_at || 0).getTime();
      return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
    })[0] || null;
}

function hasRecoverableAction(workspace = {}) {
  const recoveryOptions = asArray(workspace.recovery_options);
  return Boolean(
    workspace.recommended_action ||
      asArray(workspace.allowed_actions).length > 0 ||
      asArray(workspace.fallback_actions).length > 0 ||
      recoveryOptions.some((option) => option?.available),
  );
}

function recoverySummary(workspace = {}) {
  if (workspace.blocked_reason) return String(workspace.blocked_reason);
  const option = asArray(workspace.recovery_options).find((item) => item?.available);
  if (option?.label) return `可执行恢复动作：${option.label}`;
  if (workspace.recommended_action) return `建议执行恢复动作：${workspace.recommended_action}`;
  return "任务提供了可恢复动作，建议先处理恢复入口。";
}

function buildIssue(code, message, details = {}) {
  const evidence = asObject(details.evidence);
  const summary = details.summary || message;
  return {
    code,
    label: details.label || "状态检查",
    status: details.status || "error",
    summary,
    evidence,
    message,
    ...details,
  };
}

function terminalLabel(status) {
  if (status === "completed") return "任务已完成";
  if (status === "cancelled") return "任务已取消";
  if (status === "failed") return "任务失败";
  return "任务已结束";
}

function normalizeTimingDetail(detail = {}) {
  const source = asObject(detail);
  return {
    stage: String(source.stage || ""),
    exchangeLabel: String(source.exchange_label || source.exchangeLabel || ""),
    model: String(source.model || ""),
    durationMs: toNumber(source.duration_ms ?? source.durationMs),
    firstTokenMs: toNumber(source.first_token_ms ?? source.firstTokenMs),
    attempt: toInteger(source.attempt, 0),
    finishReason: source.finish_reason ?? source.finishReason ?? null,
    status: String(source.status || ""),
  };
}

function emptyTimingDetail() {
  return {
    stage: "",
    exchangeLabel: "",
    model: "",
    durationMs: 0,
    firstTokenMs: 0,
    attempt: 0,
    finishReason: null,
    status: "",
  };
}

function normalizeTokens(usage = {}) {
  const source = asObject(usage);
  const inputTokens = toInteger(source.input_tokens ?? source.inputTokens ?? source.prompt_tokens);
  const outputTokens = toInteger(source.output_tokens ?? source.outputTokens ?? source.completion_tokens);
  const totalTokens = toInteger(source.total_tokens ?? source.totalTokens, inputTokens + outputTokens);
  return {
    inputTokens,
    outputTokens,
    totalTokens,
    cachedTokens: toInteger(source.cached_tokens ?? source.cachedTokens),
    cacheReadInputTokens: toInteger(source.cache_read_input_tokens ?? source.cacheReadInputTokens),
  };
}

function addTokenTotals(total, usage) {
  total.inputTokens += usage.inputTokens;
  total.outputTokens += usage.outputTokens;
  total.totalTokens += usage.totalTokens;
  total.cachedTokens += usage.cachedTokens;
  total.cacheReadInputTokens += usage.cacheReadInputTokens;
}

function eventModel(event) {
  return String(event?.payload?.model || event?.model || "");
}

function isJsonParseFailedEvent(event) {
  const eventType = String(event?.event_type || "").toLowerCase();
  const message = String(event?.message || "").toLowerCase();
  const status = String(event?.payload?.status || "").toLowerCase();
  return (
    eventType.includes("json.parse.failed") ||
    eventType.includes("json_parse_failed") ||
    status.includes("json_parse_failed") ||
    message.includes("json 解析失败") ||
    message.includes("json parse failed")
  );
}

function buildStageTimingsFromReport(report = {}) {
  return Object.entries(asObject(report.timing_by_stage)).map(([stage, rawBucket]) => {
    const bucket = asObject(rawBucket);
    return {
      stage,
      callCount: toInteger(bucket.call_count ?? bucket.callCount),
      totalDurationMs: toNumber(bucket.total_duration_ms ?? bucket.totalDurationMs),
      maxDurationMs: toNumber(bucket.max_duration_ms ?? bucket.maxDurationMs),
      maxFirstTokenMs: toNumber(bucket.max_first_token_ms ?? bucket.maxFirstTokenMs),
      retryCount: toInteger(bucket.retry_count ?? bucket.retryCount),
      repairCount: toInteger(bucket.repair_count ?? bucket.repairCount),
    };
  });
}

function buildStageTimingsFromEvents(events = []) {
  const buckets = new Map();
  for (const event of asArray(events)) {
    for (const detail of asArray(event?.payload?.timing_details)) {
      const stage = String(detail?.stage || event?.stage || "unknown");
      const bucket = buckets.get(stage) || {
        stage,
        callCount: 0,
        totalDurationMs: 0,
        maxDurationMs: 0,
        maxFirstTokenMs: 0,
        retryCount: 0,
        repairCount: 0,
      };
      const durationMs = toNumber(detail?.duration_ms);
      const firstTokenMs = toNumber(detail?.first_token_ms);
      bucket.callCount += 1;
      bucket.totalDurationMs += durationMs;
      bucket.maxDurationMs = Math.max(bucket.maxDurationMs, durationMs);
      bucket.maxFirstTokenMs = Math.max(bucket.maxFirstTokenMs, firstTokenMs);
      if (detail?.is_retry) bucket.retryCount += 1;
      if (detail?.is_repair) bucket.repairCount += 1;
      buckets.set(stage, bucket);
    }
  }
  return Array.from(buckets.values());
}

function collectTimingDetailsFromEvents(events = []) {
  const details = [];
  for (const event of asArray(events)) {
    const payload = asObject(event?.payload);
    for (const rawDetail of asArray(payload.timing_details)) {
      const raw = asObject(rawDetail);
      details.push(
        normalizeTimingDetail({
          ...raw,
          stage: raw.stage || event?.stage || "",
          exchange_label: raw.exchange_label || payload.exchange_label || event?.unit_id || "",
          model: raw.model || payload.model || eventModel(event),
        }),
      );
    }
  }
  return details;
}

function slowestDurationDetail(details = []) {
  return asArray(details).reduce((slowest, detail) => {
    if (!slowest || detail.durationMs > slowest.durationMs) return detail;
    return slowest;
  }, null);
}

function slowestFirstTokenDetail(details = []) {
  return asArray(details).reduce((slowest, detail) => {
    if (detail.firstTokenMs <= 0) return slowest;
    if (!slowest || detail.firstTokenMs > slowest.firstTokenMs) return detail;
    return slowest;
  }, null);
}

function deriveLlmFromEvents(events = []) {
  const totals = {
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    cachedTokens: 0,
    cacheReadInputTokens: 0,
  };
  let requestCount = 0;
  let exchangeCount = 0;
  let cacheHitCount = 0;
  let runtimeResponseCacheHitCount = 0;
  let providerPromptCacheHitCount = 0;

  for (const event of asArray(events)) {
    if (event?.event_type === "model.usage") {
      requestCount += 1;
      const usage = normalizeTokens(event.payload);
      addTokenTotals(totals, usage);
      if (usage.cachedTokens > 0 || usage.cacheReadInputTokens > 0) {
        providerPromptCacheHitCount += 1;
      }
    }
    if (event?.event_type === "context.history.updated" || event?.event_type === "cache.hit") {
      exchangeCount += 1;
      if (event?.event_type === "cache.hit" || event?.payload?.cache_hit) {
        cacheHitCount += 1;
        runtimeResponseCacheHitCount += 1;
      }
    }
  }

  return {
    totals,
    requestCount,
    exchangeCount,
    cacheHitCount,
    runtimeResponseCacheHitCount,
    providerPromptCacheHitCount,
  };
}

function buildConnection(workspace = {}, options = {}) {
  const text = String(
    options.eventStreamState ??
      options.streamState ??
      options.connectionState ??
      workspace.event_stream_state ??
      "",
  ).trim();
  const lowerText = text.toLowerCase();

  if (/任务已完成.*事件流已关闭/.test(text) || /completed.*closed/.test(lowerText)) {
    return {
      status: "terminal_completed",
      title: "事件流已正常关闭",
      summary: "任务已完成，事件流已关闭",
      tone: "success",
      raw: text,
    };
  }
  if (/任务已取消.*事件流已关闭/.test(text) || /cancel/.test(lowerText)) {
    return {
      status: "terminal_cancelled",
      title: "事件流已关闭",
      summary: "任务已取消，事件流已关闭",
      tone: "warning",
      raw: text,
    };
  }
  if (/任务失败.*事件流已关闭/.test(text) || /failed.*closed/.test(lowerText)) {
    return {
      status: "terminal_failed",
      title: "事件流已关闭",
      summary: "任务失败，事件流已关闭",
      tone: "error",
      raw: text,
    };
  }
  if (/任务已结束.*事件流已关闭/.test(text)) {
    return {
      status: "terminal_closed",
      title: "事件流已关闭",
      summary: "任务已结束且事件流已关闭",
      tone: "default",
      raw: text,
    };
  }
  if (options.connected === true || options.opened === true || /已连接|connected|open/.test(lowerText)) {
    return {
      status: "connected",
      title: "已连接",
      summary: text || "事件流已连接。",
      tone: "success",
      raw: text,
    };
  }
  if (/重连|reconnect/.test(lowerText)) {
    return {
      status: "reconnecting",
      title: "正在重连",
      summary: text || "事件流正在重连。",
      tone: "warning",
      raw: text,
    };
  }
  if (/失败|错误|断开|手动刷新|error|failed/.test(lowerText)) {
    return {
      status: "error",
      title: "连接异常",
      summary: text || "事件流连接异常。",
      tone: "error",
      raw: text,
    };
  }
  if (options.connecting === true || /连接中|正在连接|connecting/.test(lowerText)) {
    return {
      status: "connecting",
      title: "连接中",
      summary: text || "事件流连接中。",
      tone: "default",
      raw: text,
    };
  }
  return {
    status: "unknown",
    title: "连接状态未知",
    summary: text || "暂无事件流连接状态。",
    tone: "default",
    raw: text,
  };
}

function buildHealth(workspace = {}, stateCheck) {
  const status = String(workspace?.meta?.status || "");

  if (stateCheck.status === "error") {
    return {
      status: "state_conflict",
      title: "状态不一致",
      summary: stateCheck.conflicts[0]?.message || "任务状态与诊断证据不一致。",
      tone: "error",
    };
  }
  if (hasRecoverableAction(workspace)) {
    return {
      status: "recoverable",
      title: "可恢复异常",
      summary: recoverySummary(workspace),
      tone: "warning",
    };
  }
  if (WAITING_USER_STATUSES.has(status)) {
    return {
      status: "waiting_user",
      title: "等待用户",
      summary: "任务正在等待审核、继续生成或人工处理。",
      tone: "warning",
    };
  }
  if (TERMINAL_STATUSES.has(status)) {
    return {
      status: "terminated",
      title: "已终止",
      summary: `${terminalLabel(status)}，事件流可关闭。`,
      tone: status === "completed" ? "success" : "error",
    };
  }
  if (RUNNING_STATUSES.has(status)) {
    return {
      status: "running_normal",
      title: "运行正常",
      summary: "任务正在运行，未发现状态冲突。",
      tone: "success",
    };
  }
  return {
    status: "insufficient_evidence",
    title: "证据不足",
    summary: "当前状态证据不足，暂不判定异常。",
    tone: "default",
  };
}

function buildLlm(workspace = {}) {
  const report = asObject(workspace.llm_report);
  const events = asArray(workspace.recent_events);
  const eventSummary = deriveLlmFromEvents(events);
  const hasReportUsage = Object.keys(asObject(report.usage_total)).length > 0;
  const tokens = hasReportUsage ? normalizeTokens(report.usage_total) : eventSummary.totals;
  const stageTimings = buildStageTimingsFromReport(report);
  const finalStageTimings = stageTimings.length ? stageTimings : buildStageTimingsFromEvents(events);
  const retryCount = finalStageTimings.reduce((sum, item) => sum + item.retryCount, 0);
  const repairCount = finalStageTimings.reduce((sum, item) => sum + item.repairCount, 0);
  const eventTimingDetails = collectTimingDetailsFromEvents(events);
  const eventSlowestStep = slowestDurationDetail(eventTimingDetails);
  const eventSlowestFirstToken = slowestFirstTokenDetail(eventTimingDetails);
  const newestModelEvent = latestEvent(events.filter((event) => eventModel(event)));
  const latestModel =
    String(report.latest_usage?.model || report.latest_exchange?.model || eventModel(newestModelEvent) || "");

  return {
    status: Object.keys(report).length || events.length ? "available" : "unknown",
    tokens,
    requestCount: toInteger(report.usage_count, eventSummary.requestCount),
    exchangeCount: toInteger(report.exchange_count, eventSummary.exchangeCount),
    cacheHitCount: toInteger(report.cache_hit_count, eventSummary.cacheHitCount),
    runtimeResponseCacheHitCount: toInteger(
      report.runtime_response_cache_hit_count,
      eventSummary.runtimeResponseCacheHitCount,
    ),
    providerPromptCacheHitCount: toInteger(
      report.provider_prompt_cache_hit_count,
      eventSummary.providerPromptCacheHitCount,
    ),
    retryCount,
    repairCount,
    jsonParseFailedCount: events.filter(isJsonParseFailedEvent).length,
    latestModel,
    stageTimings: finalStageTimings,
    slowestStep: Object.keys(asObject(report.slowest_step)).length
      ? normalizeTimingDetail(report.slowest_step)
      : eventSlowestStep || emptyTimingDetail(),
    slowestFirstToken: Object.keys(asObject(report.slowest_first_token)).length
      ? normalizeTimingDetail(report.slowest_first_token)
      : eventSlowestFirstToken || emptyTimingDetail(),
  };
}

function countTraceItems(items = [], key) {
  return asArray(items).reduce((sum, item) => sum + asArray(item?.[key]).length, 0);
}

function traceVerdict(summaryEntry, failedCount, traceLength) {
  if (summaryEntry?.approved === true) return "通过";
  if (summaryEntry?.approved === false) return "需处理";
  if (failedCount > 0) return "存在失败";
  if (traceLength > 0) return "待确认";
  return "暂无结论";
}

function buildAgentTrace(workspace = {}) {
  const trace = asArray(workspace.auto_review_trace);
  const currentRound = getCurrentTraceRound(trace);
  const summary = summarizeTraceRound(currentRound);
  const agentItems = asArray(summary.agentItems);
  const summaryEntry = summary.summaryEntry || null;

  return {
    status: trace.length ? "available" : "unknown",
    round: toInteger(summaryEntry?.trace_round, currentRound.round || 0),
    reviewType: String(summaryEntry?.review_type || ""),
    completedCount: summary.completedCount || 0,
    failedCount: summary.failedCount || 0,
    displayScore: summary.displayScore || 0,
    issueCount: countTraceItems(agentItems, "issues"),
    warningCount: countTraceItems(agentItems, "warnings"),
    verdict: traceVerdict(summaryEntry, summary.failedCount || 0, trace.length),
    comment: String(summaryEntry?.comment || ""),
    runCount: asArray(workspace.agent_runs).length,
  };
}

function buildRag(workspace = {}) {
  if (!hasOwn(workspace, "rag_status") || workspace.rag_status == null) {
    return {
      status: "unknown",
      title: "RAG 状态未知",
      summary: "工作区未提供 RAG 状态。",
      tone: "default",
    };
  }

  const rag = asObject(workspace.rag_status);
  if (rag.enabled === false) {
    return {
      status: "disabled",
      title: "RAG 未启用",
      summary: rag.summary || "RAG 未启用。",
      tone: "default",
      source: rag.source || "",
    };
  }
  if (rag.enabled && !rag.ready) {
    return {
      status: "not_ready",
      title: "RAG 未就绪",
      summary: rag.last_error ? `RAG 已启用但尚未就绪：${rag.last_error}` : rag.summary || "RAG 已启用但尚未就绪。",
      tone: "warning",
      source: rag.source || "",
      lastQueryStage: rag.last_query_stage || "",
    };
  }
  if (rag.ready && rag.injected) {
    const stage = rag.last_query_stage ? `，最近注入阶段：${rag.last_query_stage}` : "";
    return {
      status: "injected",
      title: "RAG 已注入",
      summary: rag.summary || `RAG 已就绪并已注入上下文${stage}。`,
      tone: "success",
      source: rag.source || "",
      lastQueryStage: rag.last_query_stage || "",
      injectionEvidence: rag.injection_evidence || "",
    };
  }
  if (rag.ready) {
    return {
      status: "ready",
      title: "RAG 已就绪",
      summary: rag.summary || "RAG 已启用且索引可用。",
      tone: "success",
      source: rag.source || "",
      lastQueryStage: rag.last_query_stage || "",
    };
  }
  return {
    status: "unknown",
    title: "RAG 状态未知",
    summary: rag.summary || "RAG 状态证据不足。",
    tone: "default",
    source: rag.source || "",
  };
}

function normalizeContextWindow(window = {}) {
  const source = asObject(window);
  return {
    maxInputTokens: toInteger(source.max_input_tokens ?? source.maxInputTokens),
    maxOutputTokens: toInteger(source.max_output_tokens ?? source.maxOutputTokens),
    maxTotalTokens: toInteger(source.max_total_tokens ?? source.maxTotalTokens),
    recommendedInputTokens: toInteger(source.recommended_input_tokens ?? source.recommendedInputTokens),
    compressionTriggerTokens: toInteger(source.compression_trigger_tokens ?? source.compressionTriggerTokens),
  };
}

function buildContextItem({ label, status = "available", summary, evidence = {} }) {
  return {
    label,
    status,
    summary,
    evidence,
  };
}

function buildContext(workspace = {}) {
  const contextStatus = Object.keys(asObject(workspace.context_status)).length
    ? asObject(workspace.context_status)
    : asObject(workspace.meta?.context_status);
  const responseCache = asObject(workspace.response_cache_status);
  const modelContextWindow = normalizeContextWindow(workspace.request_preview?.model_capabilities?.context_window);
  const hasContextStatus = Object.keys(contextStatus).length > 0;
  const hasResponseCache = Object.keys(responseCache).length > 0;
  const hasModelWindow = Object.values(modelContextWindow).some((value) => value > 0);
  const items = [];

  if (hasContextStatus) {
    items.push(
      buildContextItem({
        label: "上下文窗口",
        status: String(contextStatus.status || "available"),
        summary: contextStatus.summary || "上下文状态已提供。",
        evidence: {
          stage: contextStatus.stage || "",
          currentTokens: toInteger(contextStatus.current_tokens ?? contextStatus.currentTokens),
          inputTokens: toInteger(contextStatus.input_tokens ?? contextStatus.inputTokens),
          outputTokens: toInteger(contextStatus.output_tokens ?? contextStatus.outputTokens),
          maxInputTokens: toInteger(contextStatus.max_input_tokens ?? contextStatus.maxInputTokens),
          windowUsageRatio: toNumber(contextStatus.window_usage_ratio ?? contextStatus.windowUsageRatio),
          compressionApplied: Boolean(contextStatus.compression_applied ?? contextStatus.compressionApplied),
          cacheHit: Boolean(contextStatus.cache_hit ?? contextStatus.cacheHit),
          cacheScope: contextStatus.cache_scope || "",
        },
      }),
    );
  }

  if (hasResponseCache) {
    items.push(
      buildContextItem({
        label: "响应缓存",
        status: String(responseCache.status || (responseCache.cache_hit ? "hit" : "available")),
        summary: responseCache.summary || (responseCache.cache_hit ? "响应缓存命中。" : "响应缓存状态已提供。"),
        evidence: {
          stage: responseCache.stage || "",
          cacheHit: Boolean(responseCache.cache_hit),
          cacheScope: responseCache.cache_scope || "",
          exchangeLabel: responseCache.exchange_label || "",
          historyCount: toInteger(responseCache.history_count),
        },
      }),
    );
  }

  if (hasModelWindow) {
    items.push(
      buildContextItem({
        label: "模型上下文窗口",
        status: "available",
        summary: "模型上下文窗口能力已提供。",
        evidence: { ...modelContextWindow },
      }),
    );
  }

  if (!hasContextStatus && !hasResponseCache && !hasModelWindow) {
    return {
      status: "unknown",
      title: "上下文状态未知",
      summary: "工作区未提供上下文状态。",
      stage: "",
      stageStatus: "",
      tokens: {
        currentTokens: 0,
        inputTokens: 0,
        outputTokens: 0,
        maxInputTokens: 0,
      },
      windowUsageRatio: 0,
      compression: {
        applied: false,
        ratio: 0,
        summary: "",
      },
      cache: {
        contextCacheHit: false,
        responseCacheHit: false,
        cacheScope: "",
        cachedSegments: 0,
        responseCacheSummary: "",
        responseCacheExchangeLabel: "",
      },
      modelContextWindow,
      items,
    };
  }

  return {
    status: "available",
    title: "上下文状态",
    summary: contextStatus.summary || responseCache.summary || "上下文状态已提供。",
    stage: contextStatus.stage || responseCache.stage || "",
    stageStatus: contextStatus.status || "",
    tokens: {
      currentTokens: toInteger(contextStatus.current_tokens ?? contextStatus.currentTokens),
      inputTokens: toInteger(contextStatus.input_tokens ?? contextStatus.inputTokens),
      outputTokens: toInteger(contextStatus.output_tokens ?? contextStatus.outputTokens),
      maxInputTokens: toInteger(contextStatus.max_input_tokens ?? contextStatus.maxInputTokens),
    },
    windowUsageRatio: toNumber(contextStatus.window_usage_ratio ?? contextStatus.windowUsageRatio),
    compression: {
      applied: Boolean(contextStatus.compression_applied ?? contextStatus.compressionApplied),
      ratio: toNumber(contextStatus.compression_ratio ?? contextStatus.compressionRatio),
      summary: contextStatus.compression_summary || "",
    },
    cache: {
      contextCacheHit: Boolean(contextStatus.cache_hit ?? contextStatus.cacheHit),
      responseCacheHit: Boolean(responseCache.cache_hit),
      cacheScope: contextStatus.cache_scope || responseCache.cache_scope || "",
      cachedSegments: toInteger(contextStatus.cached_segments ?? contextStatus.cachedSegments),
      responseCacheSummary: responseCache.summary || "",
      responseCacheExchangeLabel: responseCache.exchange_label || "",
    },
    modelContextWindow,
    items,
  };
}

function buildEvidenceLinks(workspace = {}) {
  const stableLinks = [
    {
      category: "request",
      label: "请求快照",
      summary: "任务输入和模型配置摘要。",
      path: "request.json",
    },
    {
      category: "trace",
      label: "当前 Trace",
      summary: "当前 Agent Trace 轮次摘要。",
      path: "trace/current.json",
    },
    {
      category: "context",
      label: "上下文历史",
      summary: "上下文历史与缓存摘要。",
      path: "context/history.json",
    },
    {
      category: "artifact",
      label: "产物索引",
      summary: "任务产物索引摘要。",
      path: "artifacts/index.json",
    },
  ];
  const eventLinks = asArray(workspace.recent_events)
    .filter((event) => event?.md_ref || event?.json_ref)
    .map((event) => ({
      category: "event",
      label: `${event.event_type || "事件"} 引用`,
      summary: `${event.stage || "未知阶段"} / ${event.unit_id || "全局"}`,
      path: event.json_ref || event.md_ref || "",
      eventId: event.event_id || "",
      eventType: event.event_type || "",
      stage: event.stage || "",
      unitId: event.unit_id || "",
      mdRef: event.md_ref || "",
      jsonRef: event.json_ref || "",
      createdAt: event.created_at || "",
    }));
  return [...stableLinks, ...eventLinks];
}

export function buildStateCheck(workspace = {}) {
  const status = String(workspace?.meta?.status || "");
  const currentStage = String(workspace?.meta?.current_stage || "");
  const conflicts = [];
  const warnings = [];
  const unknowns = [];
  const checks = [];

  if (WAITING_REVIEW_STATUSES.has(status) || WAITING_REVIEW_STATUSES.has(currentStage)) {
    if (!hasOwn(workspace, "pending_review_summary") || workspace.pending_review_summary == null) {
      const issue = buildIssue("pending_review_unknown", "缺少待审核摘要，无法确认等待审核状态。", {
        label: "待审核摘要",
        status: "unknown",
        evidence: {
          expected: "pending_review_summary",
        },
      });
      unknowns.push(issue);
      checks.push({ ...issue, status: "unknown" });
    } else if (workspace.pending_review_summary.present === false) {
      const issue = buildIssue("pending_review_missing", "任务处于等待审核状态，但待审核摘要明确不存在。", {
        label: "待审核摘要",
        status: "error",
        evidence: {
          expected: "pending_review_summary.present=true",
          actual: "pending_review_summary.present=false",
        },
      });
      conflicts.push(issue);
      checks.push({ ...issue, status: "error" });
    } else if (workspace.pending_review_summary.present === true) {
      checks.push({
        code: "pending_review_present",
        label: "待审核摘要",
        status: "ok",
        summary: "等待审核状态已有待审核摘要。",
        message: "等待审核状态已有待审核摘要。",
        evidence: {
          present: true,
          reviewType: workspace.pending_review_summary.review_type || "",
        },
      });
    } else {
      const issue = buildIssue("pending_review_unknown", "待审核摘要缺少 present 字段，无法确认等待审核状态。", {
        label: "待审核摘要",
        status: "unknown",
        evidence: {
          expected: "pending_review_summary.present",
        },
      });
      unknowns.push(issue);
      checks.push({ ...issue, status: "unknown" });
    }
  }

  const progress = asObject(workspace.novel_progress);
  const completedChapters = numberOrNull(progress.completed_chapter_count);
  const plannedChapters = numberOrNull(progress.planned_chapter_count);
  if (completedChapters !== null && plannedChapters !== null) {
    if (completedChapters > plannedChapters) {
      const issue = buildIssue("chapter_progress_overflow", "已完成章节数大于计划章节数。", {
        label: "章节进度",
        status: "error",
        evidence: {
          completed: completedChapters,
          planned: plannedChapters,
        },
      });
      conflicts.push(issue);
      checks.push({ ...issue, status: "error" });
    } else {
      checks.push({
        code: "chapter_progress_consistent",
        label: "章节进度",
        status: "ok",
        summary: "章节进度未超过计划章节数。",
        message: "章节进度未超过计划章节数。",
        evidence: {
          completed: completedChapters,
          planned: plannedChapters,
        },
      });
    }
  }

  if (TERMINAL_STATUSES.has(status)) {
    const runningSupervisorSubtasks = asArray(workspace.supervisor_plan?.subtasks).filter(
      (subtask) => subtask?.status === "running",
    );
    const runningAgentRuns = asArray(workspace.agent_runs).filter((run) => run?.status === "running");
    if (runningSupervisorSubtasks.length > 0) {
      const issue = buildIssue("terminal_supervisor_running", "任务已进入终态，但仍存在运行中的 Supervisor 子任务。", {
        label: "终态子任务",
        status: "error",
        evidence: {
          runningCount: runningSupervisorSubtasks.length,
        },
      });
      conflicts.push(issue);
      checks.push({ ...issue, status: "error" });
    }
    if (runningAgentRuns.length > 0) {
      const issue = buildIssue("terminal_agent_run_running", "任务已进入终态，但仍存在运行中的 Agent 记录。", {
        label: "终态 Agent",
        status: "error",
        evidence: {
          runningCount: runningAgentRuns.length,
        },
      });
      conflicts.push(issue);
      checks.push({ ...issue, status: "error" });
    }
    if (!runningSupervisorSubtasks.length && !runningAgentRuns.length) {
      checks.push({
        code: "terminal_children_stopped",
        label: "终态子任务",
        status: "ok",
        summary: "终态任务未发现运行中的子任务或 Agent。",
        message: "终态任务未发现运行中的子任务或 Agent。",
        evidence: {
          runningSupervisorSubtaskCount: 0,
          runningAgentRunCount: 0,
        },
      });
    }
  }

  if (status === "waiting_manual_action") {
    if (hasRecoverableAction(workspace)) {
      checks.push({
        code: "manual_action_has_recovery",
        label: "人工处理",
        status: "ok",
        summary: "等待人工处理状态提供了恢复动作。",
        message: "等待人工处理状态提供了恢复动作。",
        evidence: {
          recoveryActionCount:
            asArray(workspace.allowed_actions).length +
            asArray(workspace.fallback_actions).length +
            asArray(workspace.recovery_options).filter((option) => option?.available).length,
        },
      });
    } else {
      const issue = buildIssue("manual_action_without_recovery", "等待人工处理状态没有可用恢复动作。", {
        label: "人工处理",
        status: "warning",
        evidence: {
          recoveryActionCount: 0,
        },
      });
      warnings.push(issue);
      checks.push({ ...issue, status: "warning" });
    }
  }

  const event = latestEvent(workspace.recent_events);
  if (event?.stage && currentStage && event.stage !== currentStage && !TERMINAL_STATUSES.has(status)) {
    const issue = buildIssue("latest_event_stage_mismatch", "最近事件阶段与当前阶段不同，仅作为提示。", {
      label: "最近事件阶段",
      status: "warning",
      evidence: {
        eventStage: event.stage,
        currentStage,
      },
    });
    warnings.push(issue);
    checks.push({ ...issue, status: "warning" });
  }

  const resultStatus = conflicts.length
    ? "error"
    : warnings.length
      ? "warning"
      : unknowns.length
        ? "unknown"
        : "ok";

  return {
    status: resultStatus,
    title: resultStatus === "error"
      ? "状态不一致"
      : resultStatus === "warning"
        ? "存在提示"
        : resultStatus === "unknown"
          ? "证据不足"
          : "状态对账正常",
    summary: conflicts[0]?.message || warnings[0]?.message || unknowns[0]?.message || "未发现状态冲突。",
    conflicts,
    warnings,
    unknowns,
    items: checks.map((item) => ({
      code: item.code || "",
      label: item.label || "状态检查",
      status: item.status || "unknown",
      summary: item.summary || item.message || "",
      evidence: asObject(item.evidence),
    })),
    checks,
    latestEventStage: event?.stage || "",
  };
}

export function buildAgentDebugDiagnostics(workspace = {}, options = {}) {
  const stateCheck = buildStateCheck(workspace);
  return {
    health: buildHealth(workspace, stateCheck),
    connection: buildConnection(workspace, options),
    stateCheck,
    context: buildContext(workspace),
    llm: buildLlm(workspace),
    agentTrace: buildAgentTrace(workspace),
    rag: buildRag(workspace),
    evidenceLinks: buildEvidenceLinks(workspace),
  };
}
