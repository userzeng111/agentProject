"use client";

import { ReactNode } from "react";
import { Box, Card, CardContent, Stack, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";

export type StageNavStage = {
  label: string;
  icon?: ReactNode;
};

export type StageNavState = "done" | "current" | "upcoming";

export type StageNavResolvedItem<T extends StageNavStage = StageNavStage> = T & {
  index: number;
  state: StageNavState;
  ariaCurrent?: "step";
};

export function resolveStageNavItems<T extends StageNavStage>(
  stages: T[],
  activeStep: number,
): StageNavResolvedItem<T>[] {
  if (!stages.length) {
    return [];
  }
  const normalizedActiveStep = Math.min(Math.max(Math.trunc(activeStep), 0), stages.length - 1);
  return stages.map((stage, index) => {
    const state: StageNavState =
      index < normalizedActiveStep ? "done" : index === normalizedActiveStep ? "current" : "upcoming";
    return {
      ...stage,
      index,
      state,
      ariaCurrent: state === "current" ? "step" : undefined,
    };
  });
}

function colorForState(state: StageNavState) {
  if (state === "done") {
    return {
      bg: "success.main",
      text: "success.main",
      border: "success.main",
    };
  }
  if (state === "current") {
    return {
      bg: "primary.main",
      text: "primary.main",
      border: "primary.main",
    };
  }
  return {
    bg: "action.disabledBackground",
    text: "text.secondary",
    border: "divider",
  };
}

export function StageNav({
  stages,
  activeStep,
}: {
  stages: StageNavStage[];
  activeStep: number;
}) {
  const items = resolveStageNavItems(stages, activeStep);

  return (
    <Card variant="outlined" data-testid="stage-nav" sx={{ borderRadius: 2, minWidth: 0 }}>
      <CardContent sx={{ py: 1.5, px: { xs: 1, sm: 2 }, "&:last-child": { pb: 1.5 } }}>
        <Box
          component="nav"
          aria-label="任务阶段导航"
          sx={{
            minWidth: 0,
            overflowX: "auto",
            overflowY: "hidden",
            pb: 0.5,
          }}
        >
          <Stack
            component="ol"
            direction="row"
            spacing={1}
            sx={{
              listStyle: "none",
              m: 0,
              p: 0,
              minWidth: "max-content",
            }}
          >
            {items.map((item) => {
              const color = colorForState(item.state);
              return (
                <Stack
                  key={`${item.index}-${item.label}`}
                  component="li"
                  direction="row"
                  alignItems="center"
                  spacing={1}
                  data-stage-state={item.state}
                  aria-current={item.ariaCurrent}
                  sx={{
                    flexShrink: 0,
                    minWidth: 92,
                    px: 1,
                    py: 0.5,
                    borderRadius: 1,
                    border: "1px solid",
                    borderColor: item.state === "upcoming" ? "divider" : color.border,
                    bgcolor: item.state === "current" ? "action.hover" : "transparent",
                  }}
                >
                  <Box
                    aria-hidden="true"
                    sx={{
                      width: 28,
                      height: 28,
                      borderRadius: "50%",
                      display: "grid",
                      placeItems: "center",
                      bgcolor: color.bg,
                      color: item.state === "upcoming" ? "text.secondary" : "common.white",
                      flexShrink: 0,
                    }}
                  >
                    {item.state === "done" ? <CheckCircleIcon fontSize="small" /> : (item.icon ?? item.index + 1)}
                  </Box>
                  <Typography
                    variant="caption"
                    sx={{
                      fontWeight: item.state === "current" ? 700 : 500,
                      color: color.text,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {item.label}
                  </Typography>
                </Stack>
              );
            })}
          </Stack>
        </Box>
      </CardContent>
    </Card>
  );
}
