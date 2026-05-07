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
