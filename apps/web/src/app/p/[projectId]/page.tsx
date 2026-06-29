import { Suspense } from "react";
import ProjectWorkspaceClient from "../project-workspace-client";

export async function generateStaticParams() {
  return [{ projectId: "__placeholder__" }];
}

export default function ProjectWorkspacePage() {
  return (
    <Suspense fallback={null}>
      <ProjectWorkspaceClient />
    </Suspense>
  );
}
