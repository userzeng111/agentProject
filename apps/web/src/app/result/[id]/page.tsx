import TaskResultClient from "@/features/task-result/task-result-client";

export const dynamicParams = true;
export const dynamic = "force-static";

export function generateStaticParams() {
  return [{ id: "__placeholder__" }];
}

export default function ResultPage({
  params,
}: {
  params: { id: string };
}) {
  return <TaskResultClient taskId={params.id} />;
}
