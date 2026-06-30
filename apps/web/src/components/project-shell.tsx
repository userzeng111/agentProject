"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { Box, Breadcrumbs, Chip, Container, Stack, Typography } from "@mui/material";
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
  return (
    <Container maxWidth={maxWidth} sx={{ py: 3, px: { xs: 2, sm: 3 }, minWidth: 0 }}>
      <Stack data-testid="project-shell" spacing={3} className="page-fade-in" sx={{ minWidth: 0 }}>
        <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
          {breadcrumbs.map((item, index) => {
            if (item.href) {
              return (
                <Link key={`${item.label}-${index}`} href={item.href} style={{ color: "inherit", textDecoration: "none" }}>
                  <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
                    {item.label}
                  </Typography>
                </Link>
              );
            }
            return (
              <Typography key={`${item.label}-${index}`} variant="body2">
                {item.label}
              </Typography>
            );
          })}
        </Breadcrumbs>

        {stageNav}

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

        {children}
      </Stack>
    </Container>
  );
}
