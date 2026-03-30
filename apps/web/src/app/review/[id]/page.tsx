import TaskReviewClient from "@/features/task-review/task-review-client";

export default function ReviewPage({
  params,
}: {
  params: { id: string };
}) {
  return <TaskReviewClient taskId={params.id} />;
}
