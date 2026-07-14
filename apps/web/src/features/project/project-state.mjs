/**
 * 项目状态与视图可达性逻辑
 *
 * 纯函数，无 React 依赖，所有判定基于领域状态。
 */

const PLACEHOLDER = "__placeholder__";

/**
 * 从 pathname 解析 project ID
 * 处理静态导出占位符 __placeholder__ 和 URL 编码
 */
export function resolveProjectId(pathname) {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] !== "p") return "";
  const encoded = segments[1] || "";
  if (!encoded || encoded === PLACEHOLDER) return "";
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}

// 五阶段模型
const PROJECT_STAGES = [
  { label: "创建", description: "素材与任务创建" },
  { label: "规划", description: "大纲与章节计划" },
  { label: "审核", description: "人工确认与修订" },
  { label: "创作", description: "正文生成与整理" },
  { label: "完成", description: "结果待确认" },
];

const STATUS_TO_STAGE = {
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

/**
 * 根据任务状态解析五阶段索引
 */
export function resolveProjectStageIndex(status = "") {
  return STATUS_TO_STAGE[status] ?? 0;
}

/**
 * 返回五阶段定义与当前活跃阶段索引
 */
export function resolveProjectStages(status = "") {
  return {
    stages: PROJECT_STAGES,
    activeStep: resolveProjectStageIndex(status),
  };
}

/* ── 视图可达性 ── */

/**
 * 项目视图可达性判定
 *
 * 输入任务摘要或 workspace meta，输出允许进入的视图列表与当前视图的
 * 状态（正常视图、状态页、错误页等）。
 *
 * @param {object} meta - 任务元信息
 * @param {string} meta.status - 任务状态
 * @param {string} meta.storage_state - 存储状态 ("runs" | "archive")
 * @param {string} [meta.current_stage] - 当前阶段
 * @param {string} [meta.review_type] - 待审核类型
 * @param {string} [meta.outline_phase] - 大纲批次阶段
 * @returns {ProjectAccess}
 */

/**
 * @typedef {object} ProjectAccess
 * @property {boolean} canViewWorkspace - 是否可进入工作台
 * @property {boolean} canViewReview - 是否可进入审核视图
 * @property {boolean} canViewResult - 是否可进入结果视图
 * @property {boolean} canViewArchive - 是否可进入归档视图
 * @property {string|null} workspaceBlockReason - 工作台阻挡原因
 * @property {string|null} reviewBlockReason - 审核视图阻挡原因
 * @property {string|null} resultBlockReason - 结果视图阻挡原因
 * @property {string|null} archiveBlockReason - 归档视图阻挡原因
 */

// 设计文档中明确的状态页文案
// 工作台始终可访问（可能只读）
function resolveWorkspaceBlockReason() {
  return null;
}

/**
 * 审核视图可访问性
 */
function resolveReviewBlockReason(meta) {
  const reviewStates = [
    "waiting_outline_review",
    "waiting_chapter_review",
    "waiting_verification_review",
  ];
  if (!reviewStates.includes(meta.status)) {
    return "当前任务不需要审核";
  }
  if (meta.review_type) {
    // 有 review_type 时验证匹配
    const validPairs = {
      waiting_outline_review: ["outline_review"],
      waiting_chapter_review: ["chapter_pair_review"],
      waiting_verification_review: ["verification_review"],
    };
    const allowed = validPairs[meta.status];
    if (allowed && !allowed.includes(meta.review_type)) {
      return "审核数据状态异常";
    }
  }
  return null;
}

/**
 * 结果视图可访问性
 */
function resolveResultBlockReason(meta, hasResultContent) {
  if (meta.storage_state === "archive") {
    return null; // 归档任务可查看结果
  }
  if (meta.status === "completed") {
    return null; // 已完成任务可查看结果
  }
  // 不处于终态且未归档
  if (hasResultContent !== undefined && !hasResultContent) {
    return "结果尚未生成";
  }
  return "结果尚未生成";
}

/**
 * 归档视图可访问性
 */
function resolveArchiveBlockReason(meta) {
  if (meta.storage_state === "archive") {
    return null; // 允许进入
  }
  if (meta.status === "completed") {
    return "任务已完成但尚未归档";
  }
  return "任务尚未完成";
}

/**
 * 计算项目内各视图的可访问性
 *
 * @param {object} meta
 * @param {boolean} [hasResultContent] - getResult 返回是否含有效内容
 * @returns {ProjectAccess}
 */
export function resolveProjectAccess(meta = {}, hasResultContent) {
  const workspaceBlockReason = resolveWorkspaceBlockReason();
  const reviewBlockReason = resolveReviewBlockReason(meta);
  const resultBlockReason = resolveResultBlockReason(meta, hasResultContent);
  const archiveBlockReason = resolveArchiveBlockReason(meta);

  return {
    canViewWorkspace: workspaceBlockReason === null,
    canViewReview: reviewBlockReason === null,
    canViewResult: resultBlockReason === null,
    canViewArchive: archiveBlockReason === null,
    workspaceBlockReason,
    reviewBlockReason,
    resultBlockReason,
    archiveBlockReason,
  };
}

/* ── 解析 view / tab 查询参数 ── */

const VALID_VIEWS = ["workspace", "review", "result", "archive"];
const VALID_ARCHIVE_TABS = ["overview", "outline", "read", "meta"];

/**
 * 规范化 view 查询参数
 * 非法 view 返回 null（应由调用方显示错误页）
 */
export function normalizeView(rawView) {
  if (!rawView) return "workspace";
  const lower = rawView.toLowerCase().trim();
  if (VALID_VIEWS.includes(lower)) return lower;
  return null;
}

/**
 * 规范化归档 tab 查询参数
 * 非归档视图下移除 tab；归档视图下非法 tab 返回 overview
 */
export function normalizeArchiveTab(rawTab) {
  if (!rawTab) return "overview";
  const lower = rawTab.toLowerCase().trim();
  if (VALID_ARCHIVE_TABS.includes(lower)) return lower;
  return "overview";
}
