import type { Metadata } from "next";
import { AppThemeProvider } from "@/components/app-theme-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "小说 Agent Demo",
  description: "基于 LangChain 与 LangGraph 的小说生成 demo",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <AppThemeProvider>{children}</AppThemeProvider>
      </body>
    </html>
  );
}
