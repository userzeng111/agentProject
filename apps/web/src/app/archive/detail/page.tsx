import { Suspense } from "react";
import LegacyArchiveDetailPage from "./legacy-archive-detail-page";

export default function ArchiveDetailPage() {
  return (
    <Suspense fallback={null}>
      <LegacyArchiveDetailPage />
    </Suspense>
  );
}
