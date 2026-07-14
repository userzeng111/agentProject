"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { legacyProjectHref } from "@/lib/task-routes";

export default function LegacyResultPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const href = legacyProjectHref("/result/", searchParams);
    if (href) {
      router.replace(href);
    } else {
      router.replace("/");
    }
  }, [router, searchParams]);

  return null;
}
