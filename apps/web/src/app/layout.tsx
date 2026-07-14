import type { Metadata } from "next";
import { ClientLayout } from "./client-layout";
import "@xyflow/react/dist/style.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "小说工坊 | AI 辅助小说创作",
  description: "基于 LangChain 与 LangGraph 的 AI 辅助小说创作系统",
  openGraph: {
    title: "小说工坊 | AI 辅助小说创作",
    description: "基于 LangChain 与 LangGraph 的 AI 辅助小说创作系统",
    images: ["/og-default.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <ClientLayout>{children}</ClientLayout>
      </body>
    </html>
  );
}
