"use client";

import React from "react";
import { Chip } from "@mui/material";
import { keyframes } from "@mui/material/styles";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ScheduleIcon from "@mui/icons-material/Schedule";
import ErrorIcon from "@mui/icons-material/Error";
import PauseCircleIcon from "@mui/icons-material/PauseCircle";

type StageStatus = "running" | "completed" | "waiting" | "failed" | "paused";

interface StageBadgeProps {
  status: StageStatus;
  label?: string;
  size?: "small" | "medium";
}

const pulse = keyframes`
  0% { opacity: 1; }
  50% { opacity: 0.5; }
  100% { opacity: 1; }
`;

const STATUS_CONFIG: Record<
  StageStatus,
  { label: string; color: "success" | "warning" | "error" | "default" | "primary"; icon: React.ReactElement }
> = {
  running: { label: "运行中", color: "success", icon: <PlayArrowIcon /> },
  completed: { label: "已完成", color: "success", icon: <CheckCircleIcon /> },
  waiting: { label: "待处理", color: "warning", icon: <ScheduleIcon /> },
  failed: { label: "失败", color: "error", icon: <ErrorIcon /> },
  paused: { label: "已暂停", color: "default", icon: <PauseCircleIcon /> },
};

export function StageBadge({ status, label, size = "small" }: StageBadgeProps) {
  const config = STATUS_CONFIG[status];

  return (
    <Chip
      icon={config.icon}
      label={label ?? config.label}
      color={config.color}
      size={size}
      sx={{
        fontWeight: 500,
        animation: status === "running" ? `${pulse} 1.5s ease-in-out infinite` : "none",
        "@media (prefers-reduced-motion: reduce)": {
          animation: "none",
        },
      }}
    />
  );
}

export type { StageStatus };
