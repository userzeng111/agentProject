"use client";

import { useEffect } from "react";
import { ErrorFallback } from "@/components/error-fallback";

/**
 * 路由级错误边界。
 *
 * 当子路由发生错误时显示，保留顶栏和整体布局。
 * 可使用 MUI 组件，因为此组件运行在 root layout 内部。
 */

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 将错误上报到日志服务
    console.error("[ErrorBoundary] 路由发生错误:", error);
  }, [error]);

  return <ErrorFallback error={error} onRetry={reset} />;
}
