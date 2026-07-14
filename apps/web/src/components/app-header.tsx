"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  Button,
  Container,
  useTheme,
  useMediaQuery,
  alpha,
} from "@mui/material";
import { Create as CreateIcon, Home as HomeIcon, Archive as ArchiveIcon, SmartToy as ChatIcon, Settings as SettingsIcon } from "@mui/icons-material";
import { homeHref, newProjectHref, archiveListHref, chatHref, settingsHref } from "@/lib/task-routes";

const NAV_LINKS = [
  { label: "首页", href: homeHref(), icon: <HomeIcon fontSize="small" /> },
  { label: "AI 对话", href: chatHref(), icon: <ChatIcon fontSize="small" /> },
  { label: "创建任务", href: newProjectHref(), icon: <CreateIcon fontSize="small" /> },
  { label: "归档", href: archiveListHref(), icon: <ArchiveIcon fontSize="small" /> },
  { label: "设置", href: settingsHref(), icon: <SettingsIcon fontSize="small" /> },
];

export function AppHeader() {
  const pathname = usePathname();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));

  return (
    <AppBar
      position="sticky"
      data-testid="app-header"
      sx={(theme) => ({
        background:
          theme.palette.mode === "dark"
            ? alpha(theme.palette.background.default, 0.84)
            : alpha(theme.palette.background.paper, 0.80),
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderBottom: "1px solid",
        borderColor:
          theme.palette.mode === "dark"
            ? alpha(theme.palette.text.secondary, 0.18)
            : alpha(theme.palette.text.primary, 0.08),
        boxShadow: "none",
        color: "text.primary",
      })}
    >
      <Container maxWidth="md" sx={{ px: { xs: 1, sm: 3 } }}>
        <Toolbar
          disableGutters
          sx={{ minHeight: { xs: 56, sm: 64 }, gap: { xs: 0.5, sm: 0 }, minWidth: 0 }}
        >
          {/* 标识 */}
          <Box
            component={Link}
            href="/"
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              mr: { xs: 0.5, sm: 3 },
              flexShrink: 0,
              color: "inherit",
              textDecoration: "none",
              "&:hover": { opacity: 0.8 },
            }}
          >
            <Box
              component="span"
              sx={{
                fontSize: "1.4rem",
                lineHeight: 1,
              }}
            >
              📖
            </Box>
            {!isMobile && (
              <Typography
                variant="h6"
                sx={{
                  fontFamily: "var(--font-serif-sc)",
                  fontWeight: 600,
                  fontSize: "1.1rem",
                  color: "primary.main",
                }}
              >
                小说工坊
              </Typography>
            )}
          </Box>

          {/* 导航链接 */}
          <Box
            sx={{
              display: "flex",
              gap: { xs: 0.25, sm: 1 },
              flex: 1,
              minWidth: 0,
              justifyContent: { xs: "space-between", sm: "flex-start" },
            }}
          >
            {NAV_LINKS.map((link) => {
              const isActive =
                link.href === "/"
                  ? pathname === "/"
                  : (pathname ?? "").startsWith(link.href);
              return (
                <Button
                  key={link.href}
                  component={Link}
                  href={link.href}
                  aria-label={isMobile ? link.label : undefined}
                  startIcon={isMobile ? link.icon : undefined}
                  sx={(theme) => ({
                    color: isActive ? "primary.main" : "text.secondary",
                    fontWeight: isActive ? 600 : 400,
                    backgroundColor: isActive
                      ? alpha(theme.palette.primary.main, theme.palette.mode === "dark" ? 0.13 : 0.08)
                      : "transparent",
                    borderRadius: 2,
                    px: isMobile ? 0.5 : 2,
                    py: 1,
                    minWidth: isMobile ? 44 : 0,
                    "& .MuiButton-startIcon": isMobile
                      ? {
                          m: 0,
                        }
                      : undefined,
                    "&:hover": {
                      backgroundColor: isActive
                        ? alpha(theme.palette.primary.main, theme.palette.mode === "dark" ? 0.18 : 0.12)
                        : alpha(theme.palette.text.primary, theme.palette.mode === "dark" ? 0.08 : 0.05),
                    },
                  })}
                >
                  {isMobile ? undefined : link.label}
                </Button>
              );
            })}
          </Box>
        </Toolbar>
      </Container>
    </AppBar>
  );
}
