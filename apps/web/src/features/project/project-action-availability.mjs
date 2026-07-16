/**
 * 项目动作可用性计算
 *
 * 单一来源：根据任务状态和 workspace 数据，计算所有可用动作及其
 * 可用性、禁用原因、确认文案、目标视图和请求状态。
 */

// 异步飞行中状态
const ASYNC_IN_FLIGHT = new Set(["planning", "drafting", "assembling"]);

// 可删除状态
const DELETABLE_STATUSES = new Set([
  "created", "sources_ingested", "waiting_outline_review",
  "ready_for_batch", "waiting_chapter_review", "waiting_verification_review",
  "completed", "failed", "cancelled",
]);

// 可取消状态
const CANCELLABLE_STATUSES = new Set([
  "planning", "waiting_outline_review", "ready_for_batch",
  "drafting", "assembling", "waiting_chapter_review",
  "waiting_verification_review", "waiting_manual_action",
]);

/**
 * @typedef {object} ActionAvailability
 * @property {boolean} available
 * @property {string|null} reason - 不可用原因
 * @property {string} label - 动作按钮文案
 * @property {string} [confirmPrompt] - 确认弹窗文案
 * @property {string} [targetView] - 动作成功后的目标视图
 * @property {"idle"|"running"|"success"|"failed"} requestStatus
 */

/**
 * @typedef {object} ProjectActions
 * @property {ActionAvailability} runOrContinue - 运行/继续创作
 * @property {ActionAvailability} review - 进入审核
 * @property {ActionAvailability} viewResult - 查看结果
 * @property {ActionAvailability} archive - 确认归档
 * @property {ActionAvailability} delete - 删除任务
 * @property {ActionAvailability} cancel - 取消运行
 * @property {ActionAvailability} recover - 恢复
 */

const REVIEW_STATUSES = new Set([
  "waiting_outline_review",
  "waiting_chapter_review",
  "waiting_verification_review",
]);
const TERMINAL_STATUSES = new Set(["completed", "cancelled", "failed"]);

/**
 * 计算所有可用动作
 *
 * @param {object} meta - workspace.meta
 * @param {object} [extra] - 附加信息
 * @param {boolean} [extra.running] - 当前是否有写操作进行中
 * @param {boolean} [extra.hasValidModel] - 是否有有效模型
 * @param {string} [extra.outlinePhase] - 大纲批次阶段
 * @returns {ProjectActions}
 */
export function resolveProjectActions(meta = {}, extra = {}) {
  const status = meta.status || "";
  const storageState = meta.storage_state || "runs";
  const running = extra.running || false;
  const hasValidModel = extra.hasValidModel !== false;
  const outlinePhase = extra.outlinePhase || "";

  const inFlight = ASYNC_IN_FLIGHT.has(status);
  const isTerminal = TERMINAL_STATUSES.has(status);
  const isCompleted = status === "completed";
  const isFailed = status === "failed";
  const isCancelled = status === "cancelled";
  const isArchived = storageState === "archive";
  const isManual = status === "waiting_manual_action";
  const needsReview = REVIEW_STATUSES.has(status);

  /* 运行/继续创作 */
  const canRun = status === "created" || status === "sources_ingested";
  const canContinue = status === "ready_for_batch";
  let runOrContinue = {
    available: false,
    reason: null,
    label: "运行",
    requestStatus: "idle",
  };
  if (running) {
    runOrContinue = { available: false, reason: "操作进行中", label: "提交中...", requestStatus: "running" };
  } else if (inFlight || isManual) {
    runOrContinue = { available: false, reason: "任务正在后台运行中", label: "运行", requestStatus: "idle" };
  } else if (isTerminal) {
    runOrContinue = { available: false, reason: "任务已结束", label: isCompleted ? "已完成" : "已结束", requestStatus: "idle" };
  } else if (isArchived) {
    runOrContinue = { available: false, reason: "任务已归档", label: "归档", requestStatus: "idle" };
  } else if (canRun) {
    runOrContinue = {
      available: !running && hasValidModel,
      reason: !hasValidModel ? "请先选择创作模型" : null,
      label: "开始创作",
      confirmPrompt: null,
      requestStatus: "idle",
    };
  } else if (canContinue) {
    runOrContinue = {
      available: !running && hasValidModel,
      reason: !hasValidModel ? "请先选择创作模型" : null,
      label: "继续创作",
      confirmPrompt: null,
      requestStatus: "idle",
    };
  }

  /* 进入审核 */
  let review = {
    available: false,
    reason: null,
    label: "进入审核",
    requestStatus: "idle",
    targetView: null,
  };
  if (needsReview) {
    review = {
      available: true,
      reason: null,
      label: outlinePhase === "chapter_batches" ? "进入章节计划审核" : "进入审核",
      requestStatus: "idle",
      targetView: "review",
    };
  } else if (isCompleted) {
    review = { available: false, reason: "任务已完成无需审核", label: "审核", requestStatus: "idle" };
  } else {
    review = { available: false, reason: "当前状态不需要审核", label: "审核", requestStatus: "idle" };
  }

  /* 查看结果 */
  let viewResult = {
    available: false,
    reason: null,
    label: "查看结果",
    requestStatus: "idle",
    targetView: null,
  };
  if (isCompleted || isArchived) {
    viewResult = {
      available: true,
      reason: null,
      label: "查看结果",
      requestStatus: "idle",
      targetView: "result",
    };
  } else if (needsReview) {
    viewResult = { available: false, reason: "请先完成审核", label: "查看结果", requestStatus: "idle" };
  } else if (inFlight) {
    viewResult = { available: false, reason: "任务运行中，结果尚未生成", label: "查看结果", requestStatus: "idle" };
  } else {
    viewResult = { available: false, reason: "结果尚未生成", label: "查看结果", requestStatus: "idle" };
  }

  /* 确认归档 */
  let archive = {
    available: false,
    reason: null,
    label: "确认归档",
    requestStatus: "idle",
  };
  if (isArchived) {
    archive = { available: false, reason: "任务已归档", label: "已归档", requestStatus: "idle" };
  } else if (isCompleted) {
    archive = {
      available: !running,
      reason: running ? "操作进行中" : null,
      label: "确认归档",
      confirmPrompt: "确认将此任务归档？归档后可随时查看但不再执行。",
      requestStatus: "idle",
    };
  } else if (isFailed || isCancelled) {
    archive = { available: false, reason: "任务未完成无法归档", label: "归档", requestStatus: "idle" };
  } else {
    archive = { available: false, reason: "任务尚未完成", label: "归档", requestStatus: "idle" };
  }

  /* 删除 */
  const canDelete = DELETABLE_STATUSES.has(status) && !isArchived;
  let deleteAction = {
    available: false,
    reason: null,
    label: "删除",
    requestStatus: "idle",
  };
  if (canDelete) {
    deleteAction = {
      available: !running,
      reason: running ? "操作进行中" : null,
      label: "删除",
      confirmPrompt: resolveDeletePrompt(status),
      requestStatus: "idle",
    };
  } else if (isArchived) {
    deleteAction = { available: false, reason: "归档任务需在归档列表中删除", label: "删除", requestStatus: "idle" };
  } else {
    deleteAction = { available: false, reason: "运行中任务无法删除", label: "删除", requestStatus: "idle" };
  }

  /* 取消 */
  const canCancel = CANCELLABLE_STATUSES.has(status);
  let cancelAction = {
    available: false,
    reason: null,
    label: "取消",
    requestStatus: "idle",
  };
  if (canCancel && (inFlight || isManual)) {
    cancelAction = {
      available: !running,
      reason: running ? "操作进行中" : null,
      label: "取消运行",
      confirmPrompt: "确认取消此任务？已生成的内容不会丢失。",
      requestStatus: "idle",
    };
  } else if (canCancel && !inFlight) {
    cancelAction = { available: false, reason: "任务未在运行", label: "取消", requestStatus: "idle" };
  } else {
    cancelAction = { available: false, reason: "当前状态不允许取消", label: "取消", requestStatus: "idle" };
  }

  /* 恢复 */
  let recover = {
    available: false,
    reason: null,
    label: "恢复",
    requestStatus: "idle",
  };
  if (isManual || isFailed || isCancelled) {
    recover = {
      available: !running,
      reason: running ? "操作进行中" : null,
      label: isManual ? "查看恢复方案" : "恢复任务",
      requestStatus: "idle",
    };
  } else {
    recover = { available: false, reason: "当前状态不需要恢复", label: "恢复", requestStatus: "idle" };
  }

  return {
    runOrContinue,
    review,
    viewResult,
    archive,
    delete: deleteAction,
    cancel: cancelAction,
    recover,
  };
}

function resolveDeletePrompt(status) {
  const prompts = {
    waiting_chapter_review: "该任务已有章节生成，删除后将丢失所有已生成内容。确认删除？",
    waiting_verification_review: "该任务已有章节生成，删除后将丢失所有已生成内容。确认删除？",
    waiting_outline_review: "该任务大纲已生成，删除后将丢失大纲内容。确认删除？",
    created: "该任务尚未开始编写，确认删除？",
    sources_ingested: "该任务尚未开始编写，确认删除？",
    failed: "该任务执行失败，确认删除？",
    cancelled: "确认删除该已取消的任务？",
    ready_for_batch: "该任务已有部分进度，删除后将丢失已生成内容。确认删除？",
    completed: "该已完成任务将删除全部正文、章节和执行日志。此操作不可恢复，请确认删除？",
  };
  return prompts[status] || "确认删除该任务？此操作不可恢复。";
}
