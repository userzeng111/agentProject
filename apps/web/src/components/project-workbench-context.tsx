"use client";

import type { ReactNode } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import type { ChipProps } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";

export type ProjectWorkbenchStage = {
  label: string;
  icon?: ReactNode;
};

/**
 * 项目工作台的紧凑上下文栏。
 *
 * 阶段、任务名和状态固定在桌面端左侧，正文不再被顶部说明信息挤压。
 */
export function ProjectWorkbenchContext({
  title,
  status,
  statusColor,
  stages,
  activeStep,
  taskId,
  testId = "project-workbench-context",
}: {
  title: string;
  status: string;
  statusColor?: ChipProps["color"];
  stages: ProjectWorkbenchStage[];
  activeStep: number;
  taskId?: string;
  testId?: string;
}) {
  const normalizedActiveStep = Math.min(Math.max(Math.trunc(activeStep), 0), Math.max(stages.length - 1, 0));

  return (
    <Stack
      data-testid={testId}
      spacing={1.5}
      sx={{
        position: "sticky",
        top: 0,
        p: 1.5,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 2,
        bgcolor: "background.paper",
      }}
    >
      <Box>
        <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.2 }}>
          项目追踪
        </Typography>
        <Typography variant="subtitle2" sx={{ mt: 0.5, overflowWrap: "anywhere" }}>
          {title}
        </Typography>
        {taskId ? (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5, overflowWrap: "anywhere" }}>
            {taskId}
          </Typography>
        ) : null}
      </Box>

      <Chip label={status} color={statusColor ?? "default"} size="small" variant="outlined" sx={{ alignSelf: "flex-start" }} />

      <Stack component="nav" aria-label="任务阶段" spacing={0.5}>
        {stages.map((stage, index) => {
          const state = index < normalizedActiveStep ? "done" : index === normalizedActiveStep ? "current" : "upcoming";
          return (
            <Stack
              key={`${stage.label}-${index}`}
              component="div"
              direction="row"
              spacing={1}
              alignItems="center"
              data-stage-state={state}
              aria-current={state === "current" ? "step" : undefined}
              sx={{
                minHeight: 32,
                px: 0.75,
                borderRadius: 1,
                color: state === "upcoming" ? "text.secondary" : "text.primary",
                bgcolor: state === "current" ? "action.selected" : "transparent",
                fontWeight: state === "current" ? 700 : 500,
              }}
            >
              <Box
                aria-hidden="true"
                sx={{
                  width: 22,
                  height: 22,
                  display: "grid",
                  placeItems: "center",
                  borderRadius: "50%",
                  bgcolor: state === "upcoming" ? "action.disabledBackground" : state === "current" ? "primary.main" : "success.main",
                  color: state === "upcoming" ? "text.secondary" : "common.white",
                  flexShrink: 0,
                }}
              >
                {state === "done" ? <CheckCircleIcon sx={{ fontSize: 16 }} /> : stage.icon ?? index + 1}
              </Box>
              <Typography variant="caption" sx={{ fontWeight: "inherit" }}>
                {stage.label}
              </Typography>
            </Stack>
          );
        })}
      </Stack>
    </Stack>
  );
}
