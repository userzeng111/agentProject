import TaskResultClient from "@/features/task-result/task-result-client";

export default function ResultPage({
  params,
}: {
  params: { id: string };
}) {
  return <TaskResultClient taskId={params.id} />;
}
