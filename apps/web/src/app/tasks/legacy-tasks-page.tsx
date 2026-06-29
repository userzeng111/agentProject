"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import TaskRunClient from "@/features/task-run/task-run-client";
import { workspaceHref } from "@/lib/task-routes";

export default function LegacyTasksPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const taskId = searchParams.get("id") || "";

  useEffect(() => {
    if (taskId) {
      router.replace(workspaceHref(taskId));
    }
  }, [router, taskId]);

  if (taskId) {
    return null;
  }

  return <TaskRunClient />;
}
