export function workspaceHref(taskId: string) {
  return `/tasks/?id=${encodeURIComponent(taskId)}`;
}

export function reviewHref(taskId: string) {
  return `/review/?id=${encodeURIComponent(taskId)}`;
}

export function resultHref(taskId: string) {
  return `/result/?id=${encodeURIComponent(taskId)}`;
}

export function archiveDetailHref(taskId: string) {
  return `/archive/detail/?id=${encodeURIComponent(taskId)}`;
}

export function settingsHref() {
  return "/settings";
}
