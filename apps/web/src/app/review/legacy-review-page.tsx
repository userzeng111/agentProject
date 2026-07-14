"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { legacyProjectHref } from "@/lib/task-routes";

export default function LegacyReviewPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const href = legacyProjectHref("/review/", searchParams);
    if (href) {
      router.replace(href);
    } else {
      router.replace("/");
    }
  }, [router, searchParams]);

  return null;
}
