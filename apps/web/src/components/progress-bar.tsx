"use client";

import { Box, LinearProgress, Typography } from "@mui/material";

interface ProgressBarProps {
  value: number;
  max: number;
  label?: string;
  showPercentage?: boolean;
}

export function ProgressBar({
  value,
  max,
  label,
  showPercentage = true,
}: ProgressBarProps) {
  const percentage = max > 0 ? Math.round((value / max) * 100) : 0;
  const clampedPercentage = Math.min(100, Math.max(0, percentage));

  return (
    <Box sx={{ width: "100%" }}>
      {(label || showPercentage) && (
        <Box sx={{ display: "flex", justifyContent: "space-between", mb: 1 }}>
          {label && (
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
          )}
          {showPercentage && (
            <Typography variant="body2" color="text.secondary">
              {value}/{max} ({clampedPercentage}%)
            </Typography>
          )}
        </Box>
      )}
      <LinearProgress
        variant="determinate"
        value={clampedPercentage}
        sx={{
          height: 8,
          borderRadius: 4,
          backgroundColor: (theme) => theme.palette.custom!.border,
          "& .MuiLinearProgress-bar": {
            borderRadius: 4,
            backgroundColor: (theme) => theme.palette.primary.main,
          },
        }}
      />
    </Box>
  );
}
