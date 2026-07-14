"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { legacyProjectHref } from "@/lib/task-routes";

export default function LegacyTasksPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const href = legacyProjectHref("/tasks/", searchParams);
    if (href) {
      router.replace(href);
    } else {
      // 无 ID 时跳转到首页作品库
      router.replace("/");
    }
  }, [router, searchParams]);

  return null;
}
