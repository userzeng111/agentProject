import type { Metadata } from "next";
import { AppThemeProvider } from "@/components/app-theme-provider";
import { AppHeader } from "@/components/app-header";
import { Box, Container } from "@mui/material";
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
        <AppThemeProvider>
          <Box
            sx={{
              minHeight: "100vh",
              display: "flex",
              flexDirection: "column",
              background:
                "radial-gradient(circle at top left, rgba(226, 195, 136, 0.35), transparent 32%), linear-gradient(180deg, #f7efe2 0%, #efe4cf 52%, #e2d3bb 100%)",
            }}
          >
            <AppHeader />
            <Container
              component="main"
              maxWidth="md"
              sx={{
                flex: 1,
                py: 3,
                px: { xs: 2, sm: 3 },
              }}
            >
              {children}
            </Container>
          </Box>
        </AppThemeProvider>
      </body>
    </html>
  );
}
