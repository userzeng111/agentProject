/**
 * 规范 URL 生成与旧路由兼容映射
 *
 * 所有新 helper 输出带尾斜杠 URL（匹配 next.config.mjs trailingSlash: true）。
 * 前七项只生成新规范 URL；后两项只供旧页面兼容壳使用。
 */

/** 作品库首页 */
export function homeHref(): string {
  return "/";
}

/** 新建项目 */
export function newProjectHref(): string {
  return "/new/";
}

/** 项目工作台规范地址 */
export function workspaceHref(taskId: string): string {
  return `/p/${encodeURIComponent(taskId)}/`;
}

/**
 * 项目内视图地址
 * @param view review | result | archive
 * @param options.tab 仅 archive 视图允许，白名单: overview | outline | read | meta
 */
export function projectViewHref(
  taskId: string,
  view: "review" | "result" | "archive",
  options?: { tab?: string },
): string {
  const encodedId = encodeURIComponent(taskId);
  const params = new URLSearchParams({ view });
  if (view === "archive" && options?.tab) {
    const validTabs = ["overview", "outline", "read", "meta"];
    if (validTabs.includes(options.tab)) {
      params.set("tab", options.tab);
    }
  }
  return `/p/${encodedId}/?${params.toString()}`;
}

/** 归档作品库列表 */
export function archiveListHref(): string {
  return "/archive/";
}

/** AI 对话 */
export function chatHref(): string {
  return "/chat/";
}

/** 设置 */
export function settingsHref(): string {
  return "/settings/";
}

/** RAG 语料库与索引同步设置 */
export function settingsRagHref(): string {
  return "/settings/rag/";
}

/** Gateway 模型协议设置 */
export function settingsModelsHref(): string {
  return "/settings/models/";
}

/* ── 旧路由兼容壳专用 ── */

const VALID_TABS = ["overview", "outline", "read", "meta"] as const;

/**
 * 旧项目入口到目标视图的映射（供旧页面兼容壳使用）
 * 来源白名单: /tasks/ → workspace, /review/ → review, /result/ → result, /archive/detail/ → archive
 * 来源不在白名单或 ID 缺失时返回 null
 */
export function legacyProjectHref(
  pathname: string,
  searchParams: URLSearchParams,
): string | null {
  const id = searchParams.get("id") || "";
  if (!id) return null;

  const encodedId = encodeURIComponent(id);

  if (pathname.startsWith("/tasks/")) {
    return `/p/${encodedId}/`;
  }
  if (pathname.startsWith("/review/")) {
    return `/p/${encodedId}/?view=review`;
  }
  if (pathname.startsWith("/result/")) {
    return `/p/${encodedId}/?view=result`;
  }
  if (pathname.startsWith("/archive/detail/")) {
    const tab = searchParams.get("tab") || "";
    const validTab = (VALID_TABS as readonly string[]).includes(tab) ? tab : "overview";
    return `/p/${encodedId}/?view=archive&tab=${validTab}`;
  }

  return null;
}

/**
 * 旧 /create/ 到 /new/ 的兼容跳转
 * 只保留原查询参数，不做解释
 */
export function legacyCreateHref(searchParams: URLSearchParams): string {
  const query = searchParams.toString();
  return query ? `/new/?${query}` : "/new/";
}
