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
  IconButton,
  useTheme,
  useMediaQuery,
} from "@mui/material";
import { Create as CreateIcon, Home as HomeIcon, Archive as ArchiveIcon, SmartToy as ChatIcon, Settings as SettingsIcon } from "@mui/icons-material";

const NAV_LINKS = [
  { label: "首页", href: "/", icon: <HomeIcon fontSize="small" /> },
  { label: "AI 对话", href: "/chat", icon: <ChatIcon fontSize="small" /> },
  { label: "创建任务", href: "/create", icon: <CreateIcon fontSize="small" /> },
  { label: "归档", href: "/archive", icon: <ArchiveIcon fontSize="small" /> },
  { label: "设置", href: "/settings", icon: <SettingsIcon fontSize="small" /> },
];

export function AppHeader() {
  const pathname = usePathname();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));

  return (
    <AppBar
      position="sticky"
      sx={{
        background: "rgba(255, 250, 242, 0.80)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderBottom: "1px solid rgba(29, 42, 39, 0.08)",
        boxShadow: "none",
        color: "text.primary",
      }}
    >
      <Container maxWidth="md">
        <Toolbar
          disableGutters
          sx={{ minHeight: { xs: 56, sm: 64 } }}
        >
          {/* Logo */}
          <Box
            component={Link}
            href="/"
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              mr: 3,
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

          {/* Nav Links */}
          <Box sx={{ display: "flex", gap: 1, flex: 1 }}>
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
                  startIcon={isMobile ? link.icon : undefined}
                  sx={{
                    color: isActive ? "primary.main" : "text.secondary",
                    fontWeight: isActive ? 600 : 400,
                    backgroundColor: isActive ? "rgba(39, 100, 81, 0.08)" : "transparent",
                    borderRadius: 2,
                    px: isMobile ? 1.5 : 2,
                    py: 1,
                    minWidth: 0,
                    "&:hover": {
                      backgroundColor: isActive
                        ? "rgba(39, 100, 81, 0.12)"
                        : "rgba(29, 42, 39, 0.05)",
                    },
                  }}
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
