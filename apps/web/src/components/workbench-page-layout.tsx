"use client";

import type { ReactNode } from "react";
import { Box, Container } from "@mui/material";
import { alpha, type Theme } from "@mui/material/styles";
import type { SxProps, SystemStyleObject } from "@mui/system";

type WorkbenchSlotBreakpoint = "md" | "lg" | "xl";

type WorkbenchResponsiveSlots = {
  /** 左侧导航开始显示的宽度。 */
  navigation?: WorkbenchSlotBreakpoint;
  /** 右侧摘要开始显示的宽度。 */
  aside?: WorkbenchSlotBreakpoint;
};

type WorkbenchSx = SystemStyleObject<Theme> & Record<string, string | SystemStyleObject<Theme>>;

/**
 * 工作台专用的布局阈值。
 *
 * `xl` 保持为 1440px，以便在常见的 1440px 笔记本与桌面屏幕上为主内容
 * 留出足够阅读宽度后再显示右侧摘要，不依赖 MUI 默认 1536px 的 `xl` 值。
 */
const WORKBENCH_SLOT_MIN_WIDTH: Record<WorkbenchSlotBreakpoint, number> = {
  md: 900,
  lg: 1200,
  xl: 1440,
};

type WorkbenchPageLayoutProps = {
  navigation?: ReactNode;
  header?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  aside?: ReactNode;
  /**
   * 分别设置导航与摘要的显示宽度。
   *
   * 未传时保留既有页面在 lg 宽度同时显示两侧栏的行为；例如创建页可传入
   * `{ navigation: "md", aside: "xl" }`，在中屏显示步骤导航、超宽屏显示摘要。
   */
  responsiveSlots?: WorkbenchResponsiveSlots;
  contentLabel?: string;
  testId?: string;
  contentTestId?: string;
};

function resolveGridTemplateColumns(hasNavigation: boolean, hasAside: boolean) {
  if (hasNavigation && hasAside) {
    return "13rem minmax(0, 1fr) 18rem";
  }
  if (hasNavigation) {
    return "13rem minmax(0, 1fr)";
  }
  if (hasAside) {
    return "minmax(0, 1fr) 18rem";
  }
  return "minmax(0, 1fr)";
}

function resolveResponsiveGridSx(
  hasNavigation: boolean,
  hasAside: boolean,
  navigationBreakpoint: WorkbenchSlotBreakpoint,
  asideBreakpoint: WorkbenchSlotBreakpoint,
): WorkbenchSx {
  const minWidths = [...new Set(Object.values(WORKBENCH_SLOT_MIN_WIDTH))].sort((left, right) => left - right);
  const sx: WorkbenchSx = {
    gridTemplateColumns: resolveGridTemplateColumns(false, false),
  };

  for (const minWidth of minWidths) {
    const navigationVisible = hasNavigation && minWidth >= WORKBENCH_SLOT_MIN_WIDTH[navigationBreakpoint];
    const asideVisible = hasAside && minWidth >= WORKBENCH_SLOT_MIN_WIDTH[asideBreakpoint];
    sx[`@media (min-width: ${minWidth}px)`] = {
      gridTemplateColumns: resolveGridTemplateColumns(navigationVisible, asideVisible),
    };
  }

  return sx;
}

function resolveSlotVisibilitySx(breakpoint: WorkbenchSlotBreakpoint): SxProps<Theme> {
  return {
    display: "none",
    [`@media (min-width: ${WORKBENCH_SLOT_MIN_WIDTH[breakpoint]}px)`]: {
      display: "block",
    },
  };
}

/**
 * 文档型工作台页面的统一骨架。
 *
 * 桌面端由中间工作区承担唯一纵向滚动，避免标题、卡片与整页同时滚动；
 * 窄屏仅保留工作区，页面内容仍能完整访问。
 */
export function WorkbenchPageLayout({
  navigation,
  header,
  children,
  footer,
  aside,
  responsiveSlots,
  contentLabel,
  testId,
  contentTestId,
}: WorkbenchPageLayoutProps) {
  const hasNavigation = Boolean(navigation);
  const hasAside = Boolean(aside);
  const navigationBreakpoint = responsiveSlots?.navigation ?? "lg";
  const asideBreakpoint = responsiveSlots?.aside ?? "lg";
  // 无显式配置的旧工作台沿用 lg 左栏阈值；统一由同一套 CSS 媒体查询生成栅格，
  // 防止将断点对象错误展开到 sx 顶层而退化成单列。
  const gridSx = resolveResponsiveGridSx(hasNavigation, hasAside, navigationBreakpoint, asideBreakpoint);
  const navigationVisibilitySx = resolveSlotVisibilitySx(navigationBreakpoint);
  const asideVisibilitySx = resolveSlotVisibilitySx(asideBreakpoint);

  return (
    <Container
      maxWidth="xl"
      sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", px: { xs: 1.5, sm: 2, lg: 3 } }}
    >
      <Box
        data-testid={testId}
        sx={{
          flex: 1,
          minHeight: 0,
          py: { xs: 1.5, sm: 2 },
          display: "grid",
          ...gridSx,
          gap: { xs: 1.5, lg: 2 },
        }}
      >
        {navigation ? (
          <Box component="aside" sx={{ ...navigationVisibilitySx, minWidth: 0, minHeight: 0 }}>
            {navigation}
          </Box>
        ) : null}

        <Box
          component="section"
          sx={(theme) => ({
            minWidth: 0,
            minHeight: 0,
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
            borderRadius: { xs: 2, sm: 3 },
            border: "1px solid",
            borderColor: "divider",
            bgcolor: alpha(theme.palette.background.paper, theme.palette.mode === "light" ? 0.86 : 0.8),
            boxShadow:
              theme.palette.mode === "light"
                ? "0 10px 28px rgba(60, 50, 35, 0.08)"
                : "0 10px 28px rgba(0, 0, 0, 0.24)",
          })}
        >
          {header ? <Box sx={{ flexShrink: 0 }}>{header}</Box> : null}
          <Box
            role="region"
            aria-label={contentLabel ?? "页面内容"}
            data-testid={contentTestId ?? (testId ? `${testId}-content` : undefined)}
            sx={{
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              overflowX: "hidden",
              overscrollBehavior: "contain",
              scrollbarGutter: "stable",
              px: { xs: 1.5, sm: 2.5, lg: 3 },
              py: { xs: 1.5, sm: 2.5, lg: 3 },
            }}
          >
            {children}
          </Box>
          {footer ? <Box sx={{ flexShrink: 0 }}>{footer}</Box> : null}
        </Box>

        {aside ? (
          <Box component="aside" sx={{ ...asideVisibilitySx, minWidth: 0, minHeight: 0 }}>
            {aside}
          </Box>
        ) : null}
      </Box>
    </Container>
  );
}
