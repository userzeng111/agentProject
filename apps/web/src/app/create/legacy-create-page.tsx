"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { legacyCreateHref } from "@/lib/task-routes";

export default function LegacyCreatePage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    router.replace(legacyCreateHref(searchParams));
  }, [router, searchParams]);

  return null;
}
