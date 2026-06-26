"use client";

import { Box, Container } from "@mui/material";
import { ReactNode } from "react";

interface PageContainerProps {
  children: ReactNode;
  maxWidth?: "xs" | "sm" | "md" | "lg" | "xl" | false;
  className?: string;
  disableAnimation?: boolean;
}

export function PageContainer({
  children,
  maxWidth = "lg",
  className,
  disableAnimation = false,
}: PageContainerProps) {
  return (
    <Container
      maxWidth={maxWidth}
      className={`${disableAnimation ? "" : "page-fade-in"} ${className ?? ""}`}
      sx={{
        py: { xs: 2, md: 4 },
        px: { xs: 2, md: 3 },
      }}
    >
      <Box sx={{ width: "100%" }}>{children}</Box>
    </Container>
  );
}
