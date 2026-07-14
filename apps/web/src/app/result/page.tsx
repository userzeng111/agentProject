import { Suspense } from "react";
import LegacyResultPage from "./legacy-result-page";

export default function ResultPage() {
  return (
    <Suspense fallback={null}>
      <LegacyResultPage />
    </Suspense>
  );
}
