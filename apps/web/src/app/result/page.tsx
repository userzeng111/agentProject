import { Suspense } from "react";
import TaskResultClient from "@/features/task-result/task-result-client";

export default function ResultPage() {
  return (
    <Suspense fallback={null}>
      <TaskResultClient />
    </Suspense>
  );
}
