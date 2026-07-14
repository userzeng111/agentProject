export const CHECK_IDS = [
  "gateway_visible",
  "streaming",
  "content_output",
  "reasoning_signal",
  "context_echo",
  "json_schema",
  "novel_minimum",
];

export const CHECK_LABELS = {
  gateway_visible: "网关可见",
  streaming: "流式输出",
  content_output: "内容输出",
  reasoning_signal: "推理信号",
  context_echo: "上下文回显",
  json_schema: "结构化 JSON",
  novel_minimum: "小说任务最小能力",
};

export const VALIDATION_STATUS_LABELS = {
  unverified: "未验证",
  running: "验证中",
  verified: "已验证",
  failed: "验证失败",
  cancelled: "已取消",
};

export const CHECK_STATUS_LABELS = {
  pending: "等待",
  running: "运行中",
  passed: "通过",
  failed: "失败",
  skipped: "跳过",
};

function createInitialCheck(checkId) {
  return {
    id: checkId,
    label: CHECK_LABELS[checkId] || checkId,
    status: "pending",
    summary: "",
    failure_reason: "",
    evidence: {},
  };
}

function normalizeCheck(check) {
  if (!check || typeof check !== "object" || !CHECK_IDS.includes(check.id)) {
    return null;
  }
  return {
    ...createInitialCheck(check.id),
    ...check,
    label: check.label || CHECK_LABELS[check.id] || check.id,
    evidence: check.evidence && typeof check.evidence === "object" ? check.evidence : {},
  };
}

function mergeChecks(currentChecks, nextChecks) {
  const byId = new Map(currentChecks.map((item) => [item.id, item]));
  for (const check of nextChecks) {
    const normalized = normalizeCheck(check);
    if (normalized) {
      byId.set(normalized.id, {
        ...(byId.get(normalized.id) || createInitialCheck(normalized.id)),
        ...normalized,
      });
    }
  }
  return CHECK_IDS.map((id) => byId.get(id) || createInitialCheck(id));
}

export function createInitialValidationState(modelId = "") {
  return {
    modelId,
    runId: "",
    status: "unverified",
    checks: CHECK_IDS.map(createInitialCheck),
    report: null,
    failureReason: "",
    chatContent: "",
    reasoningSignal: false,
    reasoningChars: 0,
    usage: null,
  };
}

export function parseValidationSearch(search = "") {
  const params = new URLSearchParams(search || "");
  return {
    modelId: params.get("model") || "",
    shouldOpen: params.get("validate") === "1",
  };
}

export function buildValidationSessionMessages(modelId, runId = "") {
  return [
    {
      role: "user",
      content: `运行模型兼容性验证：${modelId}`,
    },
    {
      role: "assistant",
      content: "",
      isStreaming: true,
      validation_meta: {
        reasoningSignal: false,
        reasoningChars: 0,
        runId,
      },
    },
  ];
}

export function applyValidationChatChunkToMessage(message, chunk) {
  const previousMeta = message?.validation_meta || {};
  const reasoningDelta = Number(chunk?.reasoning_chars_delta || 0);
  const nextReasoningChars =
    Number(previousMeta.reasoningChars || 0) + (Number.isFinite(reasoningDelta) ? reasoningDelta : 0);
  return {
    ...message,
    content: `${message?.content || ""}${typeof chunk?.content === "string" ? chunk.content : ""}`,
    validation_meta: {
      reasoningSignal: Boolean(previousMeta.reasoningSignal || chunk?.reasoning_signal || reasoningDelta > 0),
      reasoningChars: nextReasoningChars,
      runId: previousMeta.runId || chunk?.run_id || "",
    },
  };
}

export function reduceValidationEvent(state, event) {
  const data = event?.data || {};
  switch (event?.type) {
    case "validation.started":
      return {
        ...state,
        modelId: data.model_id || state.modelId,
        runId: data.run_id || state.runId,
        status: "running",
        failureReason: "",
        report: null,
        chatContent: "",
        reasoningSignal: false,
        reasoningChars: 0,
        usage: null,
      };
    case "validation.check":
      return {
        ...state,
        modelId: data.model_id || state.modelId,
        runId: data.run_id || state.runId,
        checks: mergeChecks(state.checks, data.check ? [data.check] : []),
      };
    case "validation.chat_chunk": {
      const reasoningDelta = Number(data.reasoning_chars_delta || 0);
      return {
        ...state,
        modelId: data.model_id || state.modelId,
        runId: data.run_id || state.runId,
        chatContent: `${state.chatContent || ""}${typeof data.content === "string" ? data.content : ""}`,
        reasoningSignal: Boolean(state.reasoningSignal || data.reasoning_signal || reasoningDelta > 0),
        reasoningChars: (state.reasoningChars || 0) + (Number.isFinite(reasoningDelta) ? reasoningDelta : 0),
        usage: data.usage || state.usage,
      };
    }
    case "validation.done": {
      const report = data.report || null;
      return {
        ...state,
        modelId: data.model_id || report?.model_id || state.modelId,
        runId: data.run_id || state.runId,
        status: data.status || report?.status || "verified",
        report,
        failureReason: "",
        checks: Array.isArray(report?.checks) ? mergeChecks(state.checks, report.checks) : state.checks,
      };
    }
    case "validation.error": {
      const report = data.report || null;
      const reportChecks = Array.isArray(report?.checks) ? report.checks : [];
      const fallbackCheck = data.check_id
        ? [{
            id: data.check_id,
            status: "failed",
            summary: data.message || report?.failure_reason || "验证失败",
            failure_reason: data.message || report?.failure_reason || "验证失败",
          }]
        : [];
      return {
        ...state,
        modelId: data.model_id || report?.model_id || state.modelId,
        runId: data.run_id || state.runId,
        status: "failed",
        report,
        failureReason: data.message || report?.failure_reason || "验证失败",
        checks: mergeChecks(state.checks, reportChecks.length ? reportChecks : fallbackCheck),
      };
    }
    case "validation.cancelled":
      return {
        ...state,
        status: "cancelled",
        report: null,
        failureReason: data.message || "用户取消验证",
      };
    default:
      return state;
  }
}

export function buildValidationChatUrl(modelId) {
  return `/chat?model=${encodeURIComponent(modelId)}&validate=1`;
}

export function extractCompatibilityErrorModelId(message) {
  const text = String(message || "");
  const match = text.match(/模型\s+(.+?)\s+未完成(?:小说工作流)?兼容性验证/);
  return match ? match[1].trim() : "";
}

export function getValidationLinkFromError(message, modelId) {
  const text = String(message || "");
  const targetModel = extractCompatibilityErrorModelId(text) || String(modelId || "").trim();
  if (!targetModel) {
    return null;
  }
  const isCompatibilityError =
    /未完成.*兼容性验证/.test(text) ||
    /暂不支持小说任务流/.test(text) ||
    /小说工作流兼容性验证/.test(text) ||
    /小说任务流兼容性验证/.test(text);
  return isCompatibilityError ? buildValidationChatUrl(targetModel) : null;
}
