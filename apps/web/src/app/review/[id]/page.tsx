import TaskReviewClient from "@/features/task-review/task-review-client";

export const dynamicParams = true;
export const dynamic = "force-static";

export function generateStaticParams() {
  return [{ id: "__placeholder__" }];
}

export default function ReviewPage({
  params,
}: {
  params: { id: string };
}) {
  return <TaskReviewClient taskId={params.id} />;
}
