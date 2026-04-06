import { Suspense } from "react";
import ArchiveDetailClient from "@/features/task-archive/archive-detail-client";

export default function ArchiveDetailPage() {
  return (
    <Suspense fallback={null}>
      <ArchiveDetailClient />
    </Suspense>
  );
}
