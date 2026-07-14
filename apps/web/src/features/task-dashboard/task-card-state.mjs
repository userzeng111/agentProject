import { projectViewHref, workspaceHref } from "@/lib/task-routes";

export function resolveTaskHref(task = {}) {
  const taskId = String(task.task_id || "");
  if (task.status === "completed") {
    return projectViewHref(taskId, "result");
  }
  if (
    task.status === "waiting_outline_review" ||
    task.status === "waiting_chapter_review" ||
    task.status === "waiting_verification_review"
  ) {
    return projectViewHref(taskId, "review");
  }
  if (task.storage_state === "archive") {
    return projectViewHref(taskId, "archive");
  }
  return workspaceHref(taskId);
}
