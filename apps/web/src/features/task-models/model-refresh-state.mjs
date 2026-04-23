function normalizeModelId(modelId) {
  return typeof modelId === "string" ? modelId.trim() : "";
}

function listModelIds(models) {
  return Array.isArray(models)
    ? models
        .map((model) => normalizeModelId(model?.id))
        .filter((modelId) => modelId)
    : [];
}

function formatFetchedAt(value) {
  const fetchedAt = typeof value === "string" ? value.trim() : "";
  if (!fetchedAt) {
    return "";
  }

  const date = new Date(fetchedAt);
  if (Number.isNaN(date.getTime())) {
    return fetchedAt;
  }

  return date.toISOString().replace(".000Z", "Z");
}

export function isCurrentSelectionValid(modelId, models) {
  const currentModelId = normalizeModelId(modelId);
  if (!currentModelId) {
    return false;
  }

  return new Set(listModelIds(models)).has(currentModelId);
}

export function resolveSelectionAfterRefresh({ currentModelId, availableModels }) {
  if (isCurrentSelectionValid(currentModelId, availableModels)) {
    return {
      selectedModelId: normalizeModelId(currentModelId),
      invalidated: false,
    };
  }

  return {
    selectedModelId: "",
    invalidated: Boolean(normalizeModelId(currentModelId)),
  };
}

export function formatModelRefreshStatus(meta) {
  if (meta?.loading) {
    return "正在刷新模型列表...";
  }

  const error = typeof meta?.error === "string" ? meta.error.trim() : "";
  if (error) {
    return `刷新失败：${error}`;
  }

  const attemptedRefresh = Boolean(meta?.attemptedRefresh);
  const parts = [];
  const fetchedAt = formatFetchedAt(meta?.fetchedAt);
  if (!attemptedRefresh) {
    parts.push("尚未手动刷新，当前为页面加载时获取的模型列表");
  } else if (fetchedAt) {
    parts.push(`最近拉取：${fetchedAt}`);
  }

  if (typeof meta?.cacheAgeSeconds === "number" && Number.isFinite(meta.cacheAgeSeconds)) {
    parts.push(`缓存年龄：${meta.cacheAgeSeconds} 秒`);
  }

  if (typeof meta?.cacheTtlSeconds === "number" && Number.isFinite(meta.cacheTtlSeconds)) {
    parts.push(`缓存 TTL：${meta.cacheTtlSeconds} 秒`);
  }

  if (typeof meta?.cached === "boolean") {
    parts.push(`命中缓存：${meta.cached ? "是" : "否"}`);
  }

  if (meta?.invalidated) {
    const invalidatedModelLabel =
      typeof meta?.invalidatedModelLabel === "string" && meta.invalidatedModelLabel.trim()
        ? meta.invalidatedModelLabel.trim()
        : "当前所选模型";
    parts.push(`${invalidatedModelLabel} 已失效，请手动重选模型后再创建任务`);
  }

  return parts.join(" | ") || "暂无刷新状态";
}
