"use client";

import { AppThemeProvider } from "@/components/app-theme-provider";
import { AppHeader } from "@/components/app-header";
import { NotificationProvider } from "@/components/notification-center";
import { Box } from "@mui/material";
import { usePathname } from "next/navigation";

export function ClientLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const isWorkbenchRoute = ["/new", "/create", "/archive", "/settings", "/p/"].some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );

  return (
    <AppThemeProvider>
      <NotificationProvider>
        <Box
          data-testid="root-layout-box"
          sx={{
            minHeight: "100dvh",
            height: isWorkbenchRoute ? "100dvh" : { xs: "auto", md: "100dvh" },
            overflow: isWorkbenchRoute ? "hidden" : { md: "hidden" },
            display: "flex",
            flexDirection: "column",
            background: (theme) =>
              theme.palette.mode === "light"
                ? "radial-gradient(circle at top left, rgba(226, 195, 136, 0.35), transparent 32%), linear-gradient(180deg, #f7efe2 0%, #efe4cf 52%, #e2d3bb 100%)"
                : "radial-gradient(circle at top left, rgba(39, 100, 81, 0.25), transparent 32%), linear-gradient(180deg, #0F1412 0%, #1A211E 52%, #242E2A 100%)",
          }}
        >
          <AppHeader />
          <Box
            component="main"
            sx={{
              flex: 1,
              minHeight: 0,
              display: "flex",
              flexDirection: "column",
              overflow: isWorkbenchRoute ? "hidden" : undefined,
            }}
          >
            {children}
          </Box>
        </Box>
      </NotificationProvider>
    </AppThemeProvider>
  );
}
