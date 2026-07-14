import { Suspense } from "react";
import LegacyTasksPage from "./legacy-tasks-page";

export default function TasksPage() {
  return (
    <Suspense fallback={null}>
      <LegacyTasksPage />
    </Suspense>
  );
}
