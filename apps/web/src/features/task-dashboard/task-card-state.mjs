import { projectViewHref, workspaceHref } from "@/lib/task-routes";

export const LIBRARY_TAB_VALUES = ["pending", "running", "failed", "completed"];

export function normalizeLibraryTab(value) {
  const tab = String(value || "");
  return LIBRARY_TAB_VALUES.includes(tab) ? tab : null;
}

export function resolveLibraryTabIndex(value) {
  const index = LIBRARY_TAB_VALUES.indexOf(normalizeLibraryTab(value) || "pending");
  return index >= 0 ? index : 0;
}

export function resolveLibraryTabValue(index) {
  return LIBRARY_TAB_VALUES[index] || "pending";
}

export function resolveLibraryReturnHref(value) {
  const tab = normalizeLibraryTab(value);
  return tab ? `/?library_tab=${encodeURIComponent(tab)}` : "/";
}

function withLibraryTab(href, libraryTab) {
  const normalizedTab = normalizeLibraryTab(libraryTab);
  if (!normalizedTab) return href;
  return `${href}${href.includes("?") ? "&" : "?"}library_tab=${encodeURIComponent(normalizedTab)}`;
}

export function resolveTaskHref(task = {}, libraryTab) {
  const taskId = String(task.task_id || "");
  let href;
  if (task.status === "completed") {
    href = projectViewHref(taskId, "result");
  } else if (
    task.status === "waiting_outline_review" ||
    task.status === "waiting_chapter_review" ||
    task.status === "waiting_verification_review"
  ) {
    href = projectViewHref(taskId, "review");
  } else if (task.storage_state === "archive") {
    href = projectViewHref(taskId, "archive");
  } else {
    href = workspaceHref(taskId);
  }
  return withLibraryTab(href, libraryTab);
}
