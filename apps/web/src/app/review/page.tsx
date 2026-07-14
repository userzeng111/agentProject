import { Suspense } from "react";
import LegacyReviewPage from "./legacy-review-page";

export default function ReviewPage() {
  return (
    <Suspense fallback={null}>
      <LegacyReviewPage />
    </Suspense>
  );
}
