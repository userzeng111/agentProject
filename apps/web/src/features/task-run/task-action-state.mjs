const ASYNC_IN_FLIGHT_STATUSES = new Set(["planning", "drafting", "assembling"]);
const DUPLICATE_SUBMIT_MARKERS = ["任务正在运行中", "当前任务正在执行中", "请勿重复提交"];

export function isAsyncTaskInFlight(status = "") {
  return ASYNC_IN_FLIGHT_STATUSES.has(String(status || "").trim());
}

export function resolveTaskActionSuccessMessage(task = {}, actionLabel = "任务动作") {
  const status = String(task?.status || "").trim();
  if (isAsyncTaskInFlight(status)) {
    return `${actionLabel}已提交，任务已进入后台执行，请查看实时日志。`;
  }
  if (status === "waiting_manual_action") {
    return `${actionLabel}已提交，任务需要人工处理，请查看恢复方案。`;
  }
  return `${actionLabel}已提交，状态已刷新。`;
}

export function normalizeTaskActionErrorMessage(message = "") {
  const raw = String(message || "").trim();
  if (DUPLICATE_SUBMIT_MARKERS.some((marker) => raw.includes(marker))) {
    return "任务已在后台执行，请查看实时日志或稍后刷新状态。";
  }
  return raw || "任务动作失败";
}
