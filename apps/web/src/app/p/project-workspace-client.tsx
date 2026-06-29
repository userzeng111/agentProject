"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import TaskRunClient from "@/features/task-run/task-run-client";

const STATIC_EXPORT_PLACEHOLDER = "__placeholder__";

export function resolveProjectIdFromPathname(pathname: string) {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] !== "p") {
    return "";
  }

  const encodedProjectId = segments[1] || "";
  if (!encodedProjectId || encodedProjectId === STATIC_EXPORT_PLACEHOLDER) {
    return "";
  }

  try {
    return decodeURIComponent(encodedProjectId);
  } catch {
    return encodedProjectId;
  }
}

export default function ProjectWorkspaceClient() {
  const pathname = usePathname();
  const [projectId, setProjectId] = useState<string | null>(null);

  useEffect(() => {
    setProjectId(resolveProjectIdFromPathname(window.location.pathname || pathname || ""));
  }, [pathname]);

  if (projectId === null) {
    return null;
  }

  return <TaskRunClient taskId={projectId || undefined} />;
}
