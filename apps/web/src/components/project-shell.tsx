"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { alpha, Box, Breadcrumbs, Chip, Container, Stack, Typography } from "@mui/material";
import NavigateNextIcon from "@mui/icons-material/NavigateNext";

export type ProjectShellBreadcrumb = {
  label: string;
  href?: string;
};

export type ProjectShellMetaItem = {
  label: string;
  color?: "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning";
  variant?: "filled" | "outlined";
};

export function ProjectShell({
  breadcrumbs,
  title,
  metaItems = [],
  actions,
  stageNav,
  maxWidth = "md",
  children,
}: {
  breadcrumbs: ProjectShellBreadcrumb[];
  title: string;
  metaItems?: ProjectShellMetaItem[];
  actions?: ReactNode;
  stageNav?: ReactNode;
  maxWidth?: "xs" | "sm" | "md" | "lg" | "xl" | false;
  children: ReactNode;
}) {
  const breadcrumbEl = (
    <Breadcrumbs
      separator={<NavigateNextIcon fontSize="small" />}
      sx={{
        minWidth: 0,
        maxWidth: "100%",
        "& .MuiBreadcrumbs-ol": { minWidth: 0, flexWrap: "wrap" },
        "& .MuiBreadcrumbs-li": { minWidth: 0, maxWidth: "100%" },
      }}
    >
      {breadcrumbs.map((item, index) => {
        if (item.href) {
          return (
            <Link
              key={`${item.label}-${index}`}
              href={item.href}
              style={{ color: "inherit", display: "inline-block", maxWidth: "100%", textDecoration: "none" }}
            >
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ overflowWrap: "anywhere", "&:hover": { color: "primary.main" } }}
              >
                {item.label}
              </Typography>
            </Link>
          );
        }
        return (
          <Typography key={`${item.label}-${index}`} variant="body2" sx={{ overflowWrap: "anywhere" }}>
            {item.label}
          </Typography>
        );
      })}
    </Breadcrumbs>
  );

  const titleEl = (
    <Stack
      direction={{ xs: "column", md: "row" }}
      spacing={2}
      justifyContent="space-between"
      alignItems={{ xs: "flex-start", md: "center" }}
      sx={{ minWidth: 0 }}
    >
      <Stack spacing={1} sx={{ minWidth: 0 }}>
        <Typography
          variant="h3"
          sx={{
            fontFamily: "var(--font-serif-sc)",
            overflowWrap: "anywhere",
          }}
        >
          {title}
        </Typography>
        {metaItems.length ? (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ minWidth: 0 }}>
            {metaItems.map((item, index) => (
              <Chip
                key={`${item.label}-${index}`}
                label={item.label}
                size="small"
                color={item.color ?? "default"}
                variant={item.variant}
                sx={{ maxWidth: "100%", "& .MuiChip-label": { overflowWrap: "anywhere", whiteSpace: "normal" } }}
              />
            ))}
          </Stack>
        ) : null}
      </Stack>
      {actions ? <Box sx={{ flexShrink: 0 }}>{actions}</Box> : null}
    </Stack>
  );

  return (
    <Container
      maxWidth={maxWidth}
      sx={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        py: 3,
        px: { xs: 2, sm: 3 },
        minWidth: 0,
      }}
    >
      <Stack
        data-testid="project-shell"
        spacing={3}
        className="page-fade-in"
        sx={{ flex: 1, minHeight: 0, overflow: "hidden", minWidth: 0 }}
      >
        <Box sx={{ flexShrink: 0 }}>
          {breadcrumbEl}
        </Box>

        {stageNav ? <Box sx={{ flexShrink: 0 }}>{stageNav}</Box> : null}

        <Box
          sx={{
            flexShrink: 0,
            px: 2,
            py: 1.5,
            borderRadius: 3,
            bgcolor: (theme) =>
              alpha(theme.palette.background.paper, theme.palette.mode === "light" ? 0.72 : 0.68),
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            border: 1,
            borderColor: "divider",
            boxShadow: (theme) =>
              theme.palette.mode === "light"
                ? "0 8px 24px rgba(60, 50, 35, 0.07)"
                : "0 8px 24px rgba(0, 0, 0, 0.24)",
          }}
        >
          {titleEl}
        </Box>

        <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", minWidth: 0 }}>
          {children}
        </Box>
      </Stack>
    </Container>
  );
}
