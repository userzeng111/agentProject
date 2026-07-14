import { Suspense } from "react";
import ProjectPageClient from "@/features/project/project-page-client";

export async function generateStaticParams() {
  return [{ projectId: "__placeholder__" }];
}

export default function ProjectWorkspacePage() {
  return (
    <Suspense fallback={null}>
      <ProjectPageClient />
    </Suspense>
  );
}
