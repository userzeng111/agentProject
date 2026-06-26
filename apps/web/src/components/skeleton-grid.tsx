"use client";

import { Grid, Skeleton } from "@mui/material";

interface SkeletonGridProps {
  count?: number;
  columns?: { xs?: number; sm?: number; md?: number; lg?: number };
  height?: number;
}

export function SkeletonGrid({
  count = 6,
  columns = { xs: 1, sm: 2, md: 3, lg: 3 },
  height = 160,
}: SkeletonGridProps) {
  return (
    <Grid container spacing={3}>
      {Array.from({ length: count }).map((_, index) => (
        <Grid item xs={columns.xs} sm={columns.sm} md={columns.md} lg={columns.lg} key={index}>
          <Skeleton
            variant="rounded"
            height={height}
            animation="wave"
            sx={{ borderRadius: 2 }}
          />
        </Grid>
      ))}
    </Grid>
  );
}
