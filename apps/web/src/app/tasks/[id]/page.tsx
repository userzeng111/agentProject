import TaskRunClient from "@/features/task-run/task-run-client";

export default function TaskPage({
  params,
}: {
  params: { id: string };
}) {
  return <TaskRunClient taskId={params.id} />;
}
