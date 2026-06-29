import { Suspense } from "react";
import LegacyCreatePage from "./legacy-create-page";

export default function CreatePage() {
  return (
    <Suspense fallback={null}>
      <LegacyCreatePage />
    </Suspense>
  );
}
