import ArchiveDetailClient from "@/features/task-archive/archive-detail-client";

export const dynamicParams = true;
export const dynamic = "force-static";

export function generateStaticParams() {
  return [{ id: "__placeholder__" }];
}

export default function ArchiveDetailPage({
  params,
}: {
  params: { id: string };
}) {
  return <ArchiveDetailClient taskId={params.id} />;
}
