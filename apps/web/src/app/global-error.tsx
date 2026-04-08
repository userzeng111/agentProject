"use client";

import { useEffect } from "react";

/**
 * 全局错误边界 — 当整个应用崩溃时显示。
 *
 * 注意：global-error.tsx 会替换整个 root layout，
 * 因此不能依赖 MUI ThemeProvider，只能使用纯 HTML + 内联样式。
 */

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 将错误上报到日志服务
    console.error("[GlobalError] 应用发生严重错误:", error);
  }, [error]);

  return (
    <html lang="zh-CN">
      <body style={{ margin: 0, minHeight: "100vh" }}>
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily:
              '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
            background:
              "radial-gradient(circle at top left, rgba(226, 195, 136, 0.35), transparent 32%), linear-gradient(180deg, #f7efe2 0%, #efe4cf 52%, #e2d3bb 100%)",
            color: "#1d2a27",
          }}
        >
          <div
            style={{
              maxWidth: 480,
              width: "90%",
              padding: "48px 32px",
              background: "rgba(255, 250, 242, 0.95)",
              borderRadius: 16,
              border: "1px solid rgba(29, 42, 39, 0.08)",
              boxShadow: "0 8px 32px rgba(88, 69, 37, 0.12)",
              textAlign: "center",
            }}
          >
            {/* 错误图标 */}
            <div
              style={{
                fontSize: 56,
                lineHeight: 1,
                marginBottom: 16,
              }}
            >
              &#x26A0;&#xFE0F;
            </div>

            {/* 标题 */}
            <h1
              style={{
                fontFamily: '"Songti SC", "STSong", "Noto Serif CJK SC", serif',
                fontSize: 24,
                fontWeight: 600,
                margin: "0 0 12px",
                color: "#1d2a27",
              }}
            >
              应用遇到了严重错误
            </h1>

            {/* 说明文字 */}
            <p
              style={{
                fontSize: 15,
                lineHeight: 1.6,
                color: "rgba(29, 42, 39, 0.72)",
                margin: "0 0 8px",
              }}
            >
              很抱歉，页面发生了意外崩溃。你可以尝试重新加载，或者返回首页。
            </p>

            {/* 错误详情（开发模式下显示） */}
            {error.message && (
              <div
                style={{
                  margin: "16px 0",
                  padding: "12px 16px",
                  background: "#fce8e6",
                  borderRadius: 8,
                  fontSize: 13,
                  lineHeight: 1.5,
                  color: "#b44a3f",
                  textAlign: "left",
                  wordBreak: "break-word",
                  whiteSpace: "pre-wrap",
                  border: "1px solid rgba(180, 74, 63, 0.12)",
                }}
              >
                {error.message}
              </div>
            )}

            {/* 按钮区域 */}
            <div style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 24 }}>
              {/* 重新加载按钮 */}
              <button
                onClick={() => reset()}
                style={{
                  padding: "10px 24px",
                  borderRadius: 12,
                  border: "none",
                  background: "#276451",
                  color: "#fff",
                  fontSize: 15,
                  fontWeight: 500,
                  cursor: "pointer",
                  boxShadow: "0 2px 8px rgba(88, 69, 37, 0.18)",
                  transition: "all 0.2s ease",
                }}
                onMouseOver={(e) => {
                  (e.target as HTMLButtonElement).style.background = "#1d4d3d";
                  (e.target as HTMLButtonElement).style.boxShadow =
                    "0 4px 16px rgba(88, 69, 37, 0.22)";
                }}
                onMouseOut={(e) => {
                  (e.target as HTMLButtonElement).style.background = "#276451";
                  (e.target as HTMLButtonElement).style.boxShadow =
                    "0 2px 8px rgba(88, 69, 37, 0.18)";
                }}
              >
                重新加载
              </button>

              {/* 返回首页链接 */}
              <a
                href="/"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "10px 24px",
                  borderRadius: 12,
                  border: "1px solid rgba(29, 42, 39, 0.18)",
                  background: "transparent",
                  color: "#1d2a27",
                  fontSize: 15,
                  fontWeight: 500,
                  textDecoration: "none",
                  transition: "all 0.2s ease",
                }}
              >
                返回首页
              </a>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
