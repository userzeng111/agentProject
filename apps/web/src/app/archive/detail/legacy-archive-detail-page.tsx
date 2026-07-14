"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { legacyProjectHref } from "@/lib/task-routes";

export default function LegacyArchiveDetailPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const href = legacyProjectHref("/archive/detail/", searchParams);
    if (href) {
      router.replace(href);
    } else {
      router.replace("/archive/");
    }
  }, [router, searchParams]);

  return null;
}
