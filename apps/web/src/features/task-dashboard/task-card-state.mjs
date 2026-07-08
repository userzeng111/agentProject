function resultHref(taskId) {
  return `/result/?id=${encodeURIComponent(taskId)}`;
}

function archiveDetailHref(taskId) {
  return `/archive/detail/?id=${encodeURIComponent(taskId)}`;
}

function reviewHref(taskId) {
  return `/review/?id=${encodeURIComponent(taskId)}`;
}

function workspaceHref(taskId) {
  return `/p/${encodeURIComponent(taskId)}`;
}

export function resolveTaskHref(task = {}) {
  const taskId = String(task.task_id || "");
  if (task.status === "completed") {
    return resultHref(taskId);
  }
  if (
    task.status === "waiting_outline_review" ||
    task.status === "waiting_chapter_review" ||
    task.status === "waiting_verification_review"
  ) {
    return reviewHref(taskId);
  }
  if (task.storage_state === "archive") {
    return archiveDetailHref(taskId);
  }
  return workspaceHref(taskId);
}
