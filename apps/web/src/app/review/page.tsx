import { Suspense } from "react";
import TaskReviewClient from "@/features/task-review/task-review-client";

export default function ReviewPage() {
  return (
    <Suspense fallback={null}>
      <TaskReviewClient />
    </Suspense>
  );
}
