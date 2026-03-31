import ArchiveDetailClient from "@/features/task-archive/archive-detail-client";

export default function ArchiveDetailPage({
  params,
}: {
  params: { id: string };
}) {
  return <ArchiveDetailClient taskId={params.id} />;
}
