import TaskRunClient from "@/features/task-run/task-run-client";

export const dynamicParams = true;
export const dynamic = "force-static";

export function generateStaticParams() {
  return [{ id: "__placeholder__" }];
}

export default function TaskPage({
  params,
}: {
  params: { id: string };
}) {
  return <TaskRunClient taskId={params.id} />;
}
