import { Suspense } from "react";
import TaskRunClient from "@/features/task-run/task-run-client";

export default function TasksPage() {
  return (
    <Suspense fallback={null}>
      <TaskRunClient />
    </Suspense>
  );
}
