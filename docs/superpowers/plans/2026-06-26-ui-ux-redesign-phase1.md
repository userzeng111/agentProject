# UI/UX 体验重塑 — 阶段 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立统一的设计系统（Design Token、深色模式、字体）和通用组件层（PageContainer、StageBadge、ProgressBar、EmptyState、LoadingOverlay、SkeletonGrid、ConfirmDialog、NotificationCenter、DecisionBar、ModelSelect），为后续页面重构奠定基础。

**Architecture:** 通过 MUI 5 Theme 扩展注入自定义 Design Token，使用 React Context 管理主题模式与全局通知，将当前分散在各页面的重复 UI 逻辑收敛为通用组件。本阶段只改主题与组件，不改页面结构，降低回归风险。

**Tech Stack:** Next.js 14 App Router, React 18, TypeScript, MUI 5, @emotion/react, Node.js 内置 test runner, Playwright

**参考规格：** `docs/superpowers/specs/2026-06-26-ui-ux-redesign-design.md`。本计划为规格的阶段 1 具体执行，若两者细节不一致，以本计划为准。

---

## 文件结构映射

### 新增文件

| 文件 | 职责 |
|------|------|
| `apps/web/src/types/mui.d.ts` | MUI Theme 自定义 Palette 类型扩展 |
| `apps/web/src/components/theme-mode-provider.tsx` | 主题模式 Context（light/dark/system） |
| `apps/web/src/lib/fonts.ts` | `next/font/local` 本地字体配置 |
| `apps/web/src/components/page-container.tsx` | 统一页面内容容器 |
| `apps/web/src/components/stage-badge.tsx` | 阶段状态徽章 |
| `apps/web/src/components/progress-bar.tsx` | 统一进度条 |
| `apps/web/src/components/empty-state.tsx` | 空状态组件 |
| `apps/web/src/components/loading-overlay.tsx` | 加载遮罩 |
| `apps/web/src/components/skeleton-grid.tsx` | 网格骨架屏 |
| `apps/web/src/components/confirm-dialog.tsx` | 确认对话框（替代 window.confirm） |
| `apps/web/src/components/notification-center.tsx` | 全局通知中心 |
| `apps/web/src/components/decision-bar.tsx` | 底部固定决策操作栏 |
| `apps/web/src/components/model-select.tsx` | 模型选择下拉框 |
| `apps/web/e2e/selectors.ts` | E2E 选择器常量 |
| `apps/web/e2e/helpers.ts` | E2E 通用操作辅助函数 |
| `apps/web/e2e/routes.ts` | E2E URL 模板常量 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `apps/web/src/components/app-theme-provider.tsx` | 重构为动态主题，注入 Design Token，修复 shadows 数组 |
| `apps/web/src/app/layout.tsx` | 接入 ThemeModeProvider、本地字体变量、SEO 元数据 |
| `apps/web/src/app/globals.css` | 清理重复 Token，保留动画与玻璃态类 |

---

## Task 1: MUI Theme 类型扩展

**Files:**
- Create: `apps/web/src/types/mui.d.ts`
- Test: `apps/web/src/types/mui.test.mjs`

- [ ] **Step 1: 创建类型扩展文件**

```ts
// apps/web/src/types/mui.d.ts
import '@mui/material/styles';

declare module '@mui/material/styles' {
  interface Palette {
    custom: {
      bgDefault: string;
      bgPaper: string;
      bgElevated: string;
      textPrimary: string;
      textSecondary: string;
      border: string;
    };
  }

  interface PaletteOptions {
    custom?: {
      bgDefault?: string;
      bgPaper?: string;
      bgElevated?: string;
      textPrimary?: string;
      textSecondary?: string;
      border?: string;
    };
  }
}
```

- [ ] **Step 2: 编写类型测试**

```js
// apps/web/src/types/mui.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';
import { createTheme } from '@mui/material/styles';

describe('MUI custom palette type extension', () => {
  it('should accept custom palette fields', () => {
    const theme = createTheme({
      palette: {
        custom: {
          bgDefault: '#F7EFE2',
          bgPaper: '#FFFAF2',
          bgElevated: '#FFFFFF',
          textPrimary: '#1A1612',
          textSecondary: '#5C5348',
          border: '#E5D9C8',
        },
      },
    });
    assert.strictEqual(theme.palette.custom.bgDefault, '#F7EFE2');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/types/mui.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/types/mui.d.ts apps/web/src/types/mui.test.mjs
git commit -m "feat(web): 扩展 MUI Theme 自定义 Palette 类型"
```

---

## Task 2: 主题模式 Provider

**Files:**
- Create: `apps/web/src/lib/theme-mode.ts`
- Create: `apps/web/src/components/theme-mode-provider.tsx`
- Test: `apps/web/src/lib/theme-mode.test.mjs`

- [ ] **Step 1: 创建纯逻辑模块**

```ts
// apps/web/src/lib/theme-mode.ts
export type ThemeMode = "light" | "dark" | "system";

export const STORAGE_KEY = "theme-mode";

export function getInitialMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/lib/theme-mode.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('theme-mode utilities', () => {
  it('getInitialMode should default to system when window is undefined', async () => {
    const { getInitialMode } = await import('./theme-mode.ts');
    assert.strictEqual(getInitialMode(), 'system');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/lib/theme-mode.test.mjs`
Expected: PASS

- [ ] **Step 4: 创建 ThemeModeProvider**

```tsx
// apps/web/src/components/theme-mode-provider.tsx
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  ReactNode,
} from "react";
import useMediaQuery from "@mui/material/useMediaQuery";
import { getInitialMode, type ThemeMode } from "@/lib/theme-mode";

interface ThemeModeContextValue {
  mode: ThemeMode;
  resolvedMode: "light" | "dark";
  setMode: (mode: ThemeMode) => void;
}

const ThemeModeContext = createContext<ThemeModeContextValue | null>(null);

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(getInitialMode);

  // noSsr: true 避免 SSR 期间执行媒体查询；layout.tsx 使用 suppressHydrationWarning 抑制首次渲染差异警告
  const systemPrefersDark = useMediaQuery("(prefers-color-scheme: dark)", {
    noSsr: true,
  });

  const resolvedMode: "light" | "dark" = useMemo(() => {
    if (mode === "system") {
      return systemPrefersDark ? "dark" : "light";
    }
    return mode;
  }, [mode, systemPrefersDark]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("theme-mode", next);
    }
  }, []);

  const value = useMemo(
    () => ({ mode, resolvedMode, setMode }),
    [mode, resolvedMode, setMode]
  );

  return (
    <ThemeModeContext.Provider value={value}>
      {children}
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode() {
  const ctx = useContext(ThemeModeContext);
  if (!ctx) {
    throw new Error("useThemeMode must be used within ThemeModeProvider");
  }
  return ctx;
}
```

> 注意：`ThemeModeProvider` 组件依赖 `useMediaQuery`（需要 DOM 环境），Node.js 原生 test runner 不做渲染级测试。组件渲染行为由 E2E/构建阶段覆盖。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/theme-mode.ts apps/web/src/lib/theme-mode.test.mjs apps/web/src/components/theme-mode-provider.tsx
git commit -m "feat(web): 添加主题模式工具函数与 Provider"
```

---

## Task 3: 重构 AppThemeProvider

**Files:**
- Modify: `apps/web/src/components/app-theme-provider.tsx`
- Test: `apps/web/src/components/app-theme-provider.test.mjs`

- [ ] **Step 1: 重写 AppThemeProvider**

```tsx
// apps/web/src/components/app-theme-provider.tsx
"use client";

import { CssBaseline, ThemeProvider, createTheme, type Shadows } from "@mui/material";
import { useMemo } from "react";
import { ThemeModeProvider, useThemeMode } from "./theme-mode-provider";

const LIGHT_TOKENS = {
  bgDefault: "#F7EFE2",
  bgPaper: "#FFFAF2",
  bgElevated: "#FFFFFF",
  textPrimary: "#1A1612",
  textSecondary: "#5C5348",
  border: "#E5D9C8",
};

const DARK_TOKENS = {
  bgDefault: "#0F1412",
  bgPaper: "#1A211E",
  bgElevated: "#242E2A",
  textPrimary: "#F2EEE8",
  textSecondary: "#A8A095",
  border: "#3A4540",
};

function getShadows(mode: "light" | "dark"): Shadows {
  const alpha = mode === "light" ? "0.08" : "0.35";
  const xlAlpha = mode === "light" ? "0.16" : "0.50";
  return [
    "none",
    `0 1px 2px rgba(0,0,0,${alpha})`,
    `0 2px 4px rgba(0,0,0,${alpha})`,
    `0 3px 6px rgba(0,0,0,${alpha})`,
    `0 4px 12px rgba(0,0,0,${alpha})`,
    `0 5px 14px rgba(0,0,0,${alpha})`,
    `0 6px 16px rgba(0,0,0,${alpha})`,
    `0 7px 18px rgba(0,0,0,${alpha})`,
    `0 8px 24px rgba(0,0,0,${alpha})`,
    `0 9px 26px rgba(0,0,0,${alpha})`,
    `0 10px 28px rgba(0,0,0,${alpha})`,
    `0 11px 30px rgba(0,0,0,${alpha})`,
    `0 12px 32px rgba(0,0,0,${alpha})`,
    `0 13px 34px rgba(0,0,0,${alpha})`,
    `0 14px 36px rgba(0,0,0,${alpha})`,
    `0 15px 38px rgba(0,0,0,${alpha})`,
    `0 16px 48px rgba(0,0,0,${xlAlpha})`,
    `0 17px 50px rgba(0,0,0,${xlAlpha})`,
    `0 18px 52px rgba(0,0,0,${xlAlpha})`,
    `0 19px 54px rgba(0,0,0,${xlAlpha})`,
    `0 20px 56px rgba(0,0,0,${xlAlpha})`,
    `0 21px 58px rgba(0,0,0,${xlAlpha})`,
    `0 22px 60px rgba(0,0,0,${xlAlpha})`,
    `0 23px 62px rgba(0,0,0,${xlAlpha})`,
    `0 24px 64px rgba(0,0,0,${xlAlpha})`,
  ];
}

function getDesignTokens(mode: "light" | "dark") {
  const tokens = mode === "light" ? LIGHT_TOKENS : DARK_TOKENS;
  const shadows = getShadows(mode);
  return {
    palette: {
      mode,
      primary: {
        main: mode === "light" ? "#276451" : "#4FD1A8",
        light: mode === "light" ? "#3a8a70" : "#6EE6C0",
        dark: mode === "light" ? "#1E4D3E" : "#1E4D3E",
      },
      secondary: {
        main: mode === "light" ? "#9A5F2F" : "#D4A574",
        light: mode === "light" ? "#b87a48" : "#E8C99E",
      },
      background: {
        default: tokens.bgDefault,
        paper: tokens.bgPaper,
      },
      text: {
        primary: tokens.textPrimary,
        secondary: tokens.textSecondary,
      },
      success: { main: "#2e7d5b", light: "#e8f5ee" },
      warning: { main: "#D68A1E", light: "#fef3e6" },
      error: { main: "#C0392B", light: "#fce8e6" },
      info: { main: "#4a7a8a", light: "#e6f0f3" },
      custom: {
        bgDefault: tokens.bgDefault,
        bgPaper: tokens.bgPaper,
        bgElevated: tokens.bgElevated,
        textPrimary: tokens.textPrimary,
        textSecondary: tokens.textSecondary,
        border: tokens.border,
      },
    },
    shape: { borderRadius: 10 },
    shadows: getShadows(mode),
    typography: {
      fontFamily: "var(--font-sans-sc)",
      h1: { fontFamily: "var(--font-serif-sc)" },
      h2: { fontFamily: "var(--font-serif-sc)" },
      h3: { fontFamily: "var(--font-serif-sc)" },
      h4: { fontFamily: "var(--font-serif-sc)" },
      h5: { fontFamily: "var(--font-serif-sc)" },
      h6: { fontFamily: "var(--font-serif-sc)" },
    },
    components: {
      MuiCard: {
        styleOverrides: {
          root: {
            border: `1px solid ${tokens.border}`,
            boxShadow: shadows[4],
            borderRadius: 16,
            padding: 24,
            transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
            backgroundColor: tokens.bgPaper,
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            textTransform: "none",
            paddingInline: 20,
            paddingBlock: 10,
            fontWeight: 500,
            transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
          },
          contained: {
            boxShadow: shadows[2],
            "&:hover": { boxShadow: shadows[4] },
            "&:active": { boxShadow: shadows[1] },
          },
          outlined: {
            borderColor: tokens.border,
            "&:hover": {
              borderColor: mode === "light" ? "#276451" : "#4FD1A8",
              backgroundColor: mode === "light" ? "rgba(39, 100, 81, 0.05)" : "rgba(79, 209, 168, 0.08)",
            },
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            fontWeight: 500,
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            "& .MuiOutlinedInput-root": {
              borderRadius: 10,
              transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
            },
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 16,
            backgroundImage: "none",
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            borderRadius: 16,
            boxShadow: shadows[16],
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            borderRadius: 8,
            backgroundColor: mode === "light" ? "#1A1612" : "#F2EEE8",
            color: mode === "light" ? "#F2EEE8" : "#1A1612",
          },
        },
      },
      MuiDivider: {
        styleOverrides: {
          root: {
            borderColor: tokens.border,
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: "none",
            fontWeight: 500,
            fontSize: "0.95rem",
            minHeight: 48,
            color: tokens.textSecondary,
            "&.Mui-selected": {
              color: mode === "light" ? "#276451" : "#4FD1A8",
              fontWeight: 600,
            },
          },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: {
            backgroundColor: mode === "light" ? "#276451" : "#4FD1A8",
            height: 2,
            borderRadius: 1,
          },
        },
      },
      MuiPaginationItem: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            fontWeight: 500,
            "&.Mui-selected": {
              backgroundColor: mode === "light" ? "#276451" : "#4FD1A8",
              color: "#fff",
              "&:hover": {
                backgroundColor: mode === "light" ? "#1E4D3E" : "#6EE6C0",
              },
            },
          },
        },
      },
    },
  };
}

function ThemeProviderInner({ children }: { children: React.ReactNode }) {
  const { resolvedMode } = useThemeMode();
  const theme = useMemo(
    () => createTheme(getDesignTokens(resolvedMode)),
    [resolvedMode]
  );

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </ThemeProvider>
  );
}

export function AppThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <ThemeModeProvider>
      <ThemeProviderInner>{children}</ThemeProviderInner>
    </ThemeModeProvider>
  );
}
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/app-theme-provider.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('AppThemeProvider', () => {
  it('should be importable', async () => {
    const { AppThemeProvider } = await import('./app-theme-provider.tsx');
    assert.strictEqual(typeof AppThemeProvider, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/app-theme-provider.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/app-theme-provider.tsx apps/web/src/components/app-theme-provider.test.mjs
git commit -m "feat(web): 重构 AppThemeProvider，注入 Design Token 并支持深色模式"
```

---

## Task 4: 本地字体配置（结构准备）

**Files:**
- Create: `apps/web/src/lib/fonts.ts`

- [ ] **Step 1: 创建字体配置**

```ts
// apps/web/src/lib/fonts.ts
import localFont from "next/font/local";

export const sourceHanSerif = localFont({
  // 路径相对于调用 localFont 的文件（src/lib/fonts.ts）
  // src/lib/fonts.ts → public/fonts/... 为 ../../public/fonts/...
  src: [
    {
      path: "../../public/fonts/source-han-serif-cn-400-subset.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/source-han-serif-cn-600-subset.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-serif-sc",
  display: "swap",
  fallback: ["Songti SC", "SimSun", "serif"],
});

export const sourceHanSans = localFont({
  src: [
    {
      path: "../../public/fonts/source-han-sans-cn-400-subset.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/source-han-sans-cn-500-subset.woff2",
      weight: "500",
      style: "normal",
    },
  ],
  variable: "--font-sans-sc",
  display: "swap",
  fallback: ["PingFang SC", "Microsoft YaHei", "sans-serif"],
});
```

- [ ] **Step 2: 说明**

阶段 1 仅建立 `next/font/local` 配置结构，**不实际加载本地字体文件**，原因：

- 子集化中文字体文件由后续 `scripts/subset-fonts.sh` 生成。
- 在字体文件未生成前使用 `next/font/local` 会导致构建失败或浏览器字体解码错误。
- 阶段 1 的 `layout.tsx` 继续使用 `globals.css` 中定义的系统字体回退栈。

子集化工具链：

- 使用 `fonttools` Python 库或 `subset-font` Node 库按需截取项目所需字符集。
- 构建脚本：`scripts/subset-fonts.sh`，在 CI 中运行，输出子集化文件到 `public/fonts/`。
- 子集化字体生成后，在阶段 4 启用 `next/font/local` 的 CSS 变量注入。

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/lib/fonts.ts
git commit -m "feat(web): 添加 next/font/local 本地字体配置（阶段 1 暂不启用）"
```

---

## Task 5: 更新 Root Layout

**Files:**
- Modify: `apps/web/src/app/layout.tsx`

- [ ] **Step 1: 重写 layout.tsx**

移除原有的 `<head>` 标签块，改为 `metadata` 导出；接入新的 `AppThemeProvider`、动态背景与 `NotificationProvider`。

```tsx
// apps/web/src/app/layout.tsx
import { AppThemeProvider } from "@/components/app-theme-provider";
import { AppHeader } from "@/components/app-header";
import { NotificationProvider } from "@/components/notification-center";
import { Box } from "@mui/material";
import "@xyflow/react/dist/style.css";
import "./globals.css";

export const metadata = {
  title: "小说工坊 | AI 辅助小说创作",
  description: "基于 LangChain 与 LangGraph 的 AI 辅助小说创作系统",
  openGraph: {
    title: "小说工坊 | AI 辅助小说创作",
    description: "基于 LangChain 与 LangGraph 的 AI 辅助小说创作系统",
    images: ["/og-default.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <AppThemeProvider>
          <NotificationProvider>
            <Box
              data-testid="root-layout-box"
              sx={{
                minHeight: "100vh",
                display: "flex",
                flexDirection: "column",
                background: (theme) =>
                  theme.palette.mode === "light"
                    ? "radial-gradient(circle at top left, rgba(226, 195, 136, 0.35), transparent 32%), linear-gradient(180deg, #f7efe2 0%, #efe4cf 52%, #e2d3bb 100%)"
                    : "radial-gradient(circle at top left, rgba(39, 100, 81, 0.25), transparent 32%), linear-gradient(180deg, #0F1412 0%, #1A211E 52%, #242E2A 100%)",
              }}
            >
              <AppHeader />
              <Box component="main" sx={{ flex: 1 }}>
                {children}
              </Box>
            </Box>
          </NotificationProvider>
        </AppThemeProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 2: 创建 Open Graph 占位图**

确认 `apps/web/public/og-default.png` 存在。若不存在，先创建占位图片：

```bash
# 使用 ImageMagick 生成 1200x630 的纯色占位图
convert -size 1200x630 xc:'#276451' apps/web/public/og-default.png
```

如果没有 ImageMagick，可手动放置任意 1200x630 PNG 图片到该路径。

- [ ] **Step 3: 运行构建校验**

Run: `cd apps/web && npm run build`
Expected: 成功，无 TypeScript 错误

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/layout.tsx apps/web/public/og-default.png
git commit -m "feat(web): 更新 Root Layout，接入动态背景、metadata 导出与 NotificationProvider"
```

---

## Task 6: 清理 globals.css

**Files:**
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: 精简 globals.css**

**说明**：阶段 1 先清理重复 Token，保留动画与玻璃态类。`.glass-card` 中的硬编码颜色为临时方案，阶段 4 将通过 MUI `styled` 或 `sx` 函数形式完全迁移到 Theme Token。

```css
/* apps/web/src/app/globals.css */
:root {
  /* 动画与玻璃态专用变量；颜色 Token 已迁移到 MUI Theme */
  /* 字体变量为系统字体回退栈。
     阶段 4 启用 next/font/local 后，由其通过 <html style> 注入同名 CSS 变量，
     优先级高于 :root，从而自动覆盖此处定义。 */
  --font-sans-sc: "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-serif-sc: "Songti SC", "STSong", serif;

  /* 玻璃态变量，与 Design Token 对齐；深色模式由 MUI Theme 的 sx 函数控制 */
  --glass-bg: rgba(255, 250, 242, 0.65);
  --glass-border: rgba(255, 255, 255, 0.45);
}

* {
  box-sizing: border-box;
}

html {
  min-height: 100%;
}

body {
  margin: 0;
  min-height: 100vh;
}

a {
  color: inherit;
  text-decoration: none;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
}

/* === 玻璃态卡片 === */
.glass-card {
  background: var(--glass-bg);
  backdrop-filter: blur(12px) saturate(1.2);
  -webkit-backdrop-filter: blur(12px) saturate(1.2);
  border: 1px solid var(--glass-border);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  border-radius: 16px;
}

/* === 全局过渡动画 === */
.transition-default {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

/* === 页面淡入动画 === */
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.page-fade-in {
  animation: fadeIn 0.3s cubic-bezier(0.4, 0, 0.2, 1) forwards;
}

/* === 减少动画偏好 === */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 2: 运行构建校验**

Run: `cd apps/web && npm run build`
Expected: 成功

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/globals.css
git commit -m "refactor(web): 清理 globals.css，将颜色 Token 迁移到 MUI Theme"
```

---

## Task 7: PageContainer 组件

**Files:**
- Create: `apps/web/src/components/page-container.tsx`
- Test: `apps/web/src/components/page-container.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/page-container.tsx
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
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/page-container.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('PageContainer', () => {
  it('should be importable', async () => {
    const { PageContainer } = await import('./page-container.tsx');
    assert.strictEqual(typeof PageContainer, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/page-container.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/page-container.tsx apps/web/src/components/page-container.test.mjs
git commit -m "feat(web): 添加 PageContainer 通用容器组件"
```

---

## Task 8: StageBadge 组件

**Files:**
- Create: `apps/web/src/components/stage-badge.tsx`
- Test: `apps/web/src/components/stage-badge.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/stage-badge.tsx
"use client";

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
  { label: string; color: "success" | "warning" | "error" | "default" | "primary"; icon: React.ReactNode }
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
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/stage-badge.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('StageBadge', () => {
  it('should be importable', async () => {
    const { StageBadge } = await import('./stage-badge.tsx');
    assert.strictEqual(typeof StageBadge, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/stage-badge.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/stage-badge.tsx apps/web/src/components/stage-badge.test.mjs
git commit -m "feat(web): 添加 StageBadge 阶段状态徽章组件"
```

---

## Task 9: ProgressBar 组件

**Files:**
- Create: `apps/web/src/components/progress-bar.tsx`
- Test: `apps/web/src/components/progress-bar.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/progress-bar.tsx
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
          backgroundColor: (theme) => theme.palette.custom.border,
          "& .MuiLinearProgress-bar": {
            borderRadius: 4,
            backgroundColor: (theme) => theme.palette.primary.main,
          },
        }}
      />
    </Box>
  );
}
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/progress-bar.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('ProgressBar', () => {
  it('should be importable', async () => {
    const { ProgressBar } = await import('./progress-bar.tsx');
    assert.strictEqual(typeof ProgressBar, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/progress-bar.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/progress-bar.tsx apps/web/src/components/progress-bar.test.mjs
git commit -m "feat(web): 添加 ProgressBar 进度条组件"
```

---

## Task 10: EmptyState 组件

**Files:**
- Create: `apps/web/src/components/empty-state.tsx`
- Test: `apps/web/src/components/empty-state.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/empty-state.tsx
"use client";

import { Box, Button, Typography } from "@mui/material";
import InboxIcon from "@mui/icons-material/Inbox";

interface EmptyStateProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: React.ReactNode;
}

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
  icon = <InboxIcon sx={{ fontSize: 64, color: "text.secondary", opacity: 0.5 }} />,
}: EmptyStateProps) {
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        py: 8,
        px: 2,
        textAlign: "center",
      }}
    >
      {icon}
      <Typography variant="h6" sx={{ mt: 2, fontWeight: 500 }}>
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: 400 }}>
          {description}
        </Typography>
      )}
      {actionLabel && onAction && (
        <Button variant="contained" onClick={onAction} sx={{ mt: 3 }}>
          {actionLabel}
        </Button>
      )}
    </Box>
  );
}
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/empty-state.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('EmptyState', () => {
  it('should be importable', async () => {
    const { EmptyState } = await import('./empty-state.tsx');
    assert.strictEqual(typeof EmptyState, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/empty-state.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/empty-state.tsx apps/web/src/components/empty-state.test.mjs
git commit -m "feat(web): 添加 EmptyState 空状态组件"
```

---

## Task 11: LoadingOverlay 组件

**Files:**
- Create: `apps/web/src/components/loading-overlay.tsx`
- Test: `apps/web/src/components/loading-overlay.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/loading-overlay.tsx
"use client";

import { Backdrop, CircularProgress, Typography } from "@mui/material";

interface LoadingOverlayProps {
  open: boolean;
  message?: string;
}

export function LoadingOverlay({ open, message }: LoadingOverlayProps) {
  return (
    <Backdrop
      open={open}
      sx={{
        zIndex: (theme) => theme.zIndex.modal + 1,
        display: "flex",
        flexDirection: "column",
        gap: 2,
        backgroundColor: "rgba(0, 0, 0, 0.25)",
      }}
    >
      <CircularProgress color="primary" />
      {message && (
        <Typography variant="body2" color="white">
          {message}
        </Typography>
      )}
    </Backdrop>
  );
}
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/loading-overlay.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('LoadingOverlay', () => {
  it('should be importable', async () => {
    const { LoadingOverlay } = await import('./loading-overlay.tsx');
    assert.strictEqual(typeof LoadingOverlay, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/loading-overlay.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/loading-overlay.tsx apps/web/src/components/loading-overlay.test.mjs
git commit -m "feat(web): 添加 LoadingOverlay 加载遮罩组件"
```

---

## Task 12: SkeletonGrid 组件

**Files:**
- Create: `apps/web/src/components/skeleton-grid.tsx`
- Test: `apps/web/src/components/skeleton-grid.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/skeleton-grid.tsx
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
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/skeleton-grid.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('SkeletonGrid', () => {
  it('should be importable', async () => {
    const { SkeletonGrid } = await import('./skeleton-grid.tsx');
    assert.strictEqual(typeof SkeletonGrid, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/skeleton-grid.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/skeleton-grid.tsx apps/web/src/components/skeleton-grid.test.mjs
git commit -m "feat(web): 添加 SkeletonGrid 骨架屏组件"
```

---

## Task 13: ConfirmDialog 组件

**Files:**
- Create: `apps/web/src/components/confirm-dialog.tsx`
- Test: `apps/web/src/components/confirm-dialog.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/confirm-dialog.tsx
"use client";

import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from "@mui/material";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmColor?: "primary" | "error" | "warning";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认",
  cancelLabel = "取消",
  confirmColor = "primary",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText>{message}</DialogContentText>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onCancel} variant="outlined">
          {cancelLabel}
        </Button>
        <Button onClick={onConfirm} variant="contained" color={confirmColor} autoFocus>
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/confirm-dialog.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('ConfirmDialog', () => {
  it('should be importable', async () => {
    const { ConfirmDialog } = await import('./confirm-dialog.tsx');
    assert.strictEqual(typeof ConfirmDialog, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/confirm-dialog.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/confirm-dialog.tsx apps/web/src/components/confirm-dialog.test.mjs
git commit -m "feat(web): 添加 ConfirmDialog 确认对话框组件"
```

---

## Task 14: NotificationCenter 组件

**Files:**
- Create: `apps/web/src/components/notification-center.tsx`
- Test: `apps/web/src/components/notification-center.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/notification-center.tsx
"use client";

import { useState, useCallback, useMemo, useContext, createContext, useRef } from "react";
import { Alert, Snackbar } from "@mui/material";

type NotificationType = "success" | "error" | "warning" | "info";

interface Notification {
  id: string;
  type: NotificationType;
  message: string;
  duration?: number;
  position: number;
}

interface NotificationContextValue {
  notify: (notification: Omit<Notification, "id" | "position">) => void;
  closeNotification: (id: string) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const positionRef = useRef(0);

  const notify = useCallback((notification: Omit<Notification, "id" | "position">) => {
    const position = positionRef.current++;
    setNotifications((prev) => [...prev, { ...notification, id: generateId(), position }]);
  }, []);

  const closeNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const value = useMemo(
    () => ({ notify, closeNotification }),
    [notify, closeNotification]
  );

  return (
    <NotificationContext.Provider value={value}>
      {children}
      {notifications.map((notification) => (
        <Snackbar
          key={notification.id}
          open
          autoHideDuration={notification.duration ?? 5000}
          onClose={() => closeNotification(notification.id)}
          anchorOrigin={{ vertical: "top", horizontal: "right" }}
          sx={{ mt: notification.position * 1.5 }}
        >
          <Alert
            severity={notification.type}
            onClose={() => closeNotification(notification.id)}
            sx={{ width: "100%" }}
          >
            {notification.message}
          </Alert>
        </Snackbar>
      ))}
    </NotificationContext.Provider>
  );
}

export function useNotification() {
  const ctx = useContext(NotificationContext);
  if (!ctx) {
    throw new Error("useNotification must be used within NotificationProvider");
  }
  return ctx;
}
```

> 注意：使用固定 `position` 字段避免关闭通知后剩余通知位置跳动。`positionRef` 只增不减，确保每个新通知都有唯一偏移。

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/notification-center.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('NotificationCenter', () => {
  it('should be importable', async () => {
    const { NotificationProvider, useNotification } = await import('./notification-center.tsx');
    assert.strictEqual(typeof NotificationProvider, 'function');
    assert.strictEqual(typeof useNotification, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/notification-center.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/notification-center.tsx apps/web/src/components/notification-center.test.mjs
git commit -m "feat(web): 添加 NotificationCenter 全局通知中心"
```

---

## Task 15: DecisionBar 组件

**Files:**
- Create: `apps/web/src/components/decision-bar.tsx`
- Test: `apps/web/src/components/decision-bar.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/decision-bar.tsx
"use client";

import { AppBar, Button, Toolbar } from "@mui/material";

type DecisionActionColor = "primary" | "error" | "warning" | "secondary";
type DecisionActionVariant = "contained" | "outlined";

interface DecisionAction {
  label: string;
  onClick: () => void;
  variant?: DecisionActionVariant;
  color?: DecisionActionColor;
  disabled?: boolean;
}

interface DecisionBarProps {
  actions: DecisionAction[];
}

export function DecisionBar({ actions }: DecisionBarProps) {
  return (
    <AppBar
      position="sticky"
      color="default"
      elevation={0}
      sx={{
        top: "auto",
        bottom: 0,
        zIndex: (theme) => theme.zIndex.appBar + 50,
        backgroundColor: "background.paper",
        borderTop: "1px solid",
        borderColor: "custom.border",
      }}
    >
      <Toolbar sx={{ justifyContent: "flex-end", gap: 2, px: { xs: 2, md: 3 } }}>
        {actions.map((action, index) => (
          <Button
            key={index}
            variant={action.variant ?? "outlined"}
            color={action.color ?? "primary"}
            disabled={action.disabled}
            onClick={action.onClick}
          >
            {action.label}
          </Button>
        ))}
      </Toolbar>
    </AppBar>
  );
}

export type { DecisionAction };
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/decision-bar.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('DecisionBar', () => {
  it('should be importable', async () => {
    const { DecisionBar } = await import('./decision-bar.tsx');
    assert.strictEqual(typeof DecisionBar, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/decision-bar.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/decision-bar.tsx apps/web/src/components/decision-bar.test.mjs
git commit -m "feat(web): 添加 DecisionBar 底部决策操作栏组件"
```

---

## Task 16: ModelSelect 组件

**Files:**
- Create: `apps/web/src/components/model-select.tsx`
- Test: `apps/web/src/components/model-select.test.mjs`

- [ ] **Step 1: 创建组件**

```tsx
// apps/web/src/components/model-select.tsx
"use client";

import {
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  type SelectChangeEvent,
} from "@mui/material";

interface ModelOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface ModelSelectProps {
  label: string;
  value: string;
  options: ModelOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  size?: "small" | "medium";
}

export function ModelSelect({
  label,
  value,
  options,
  onChange,
  disabled = false,
  size = "small",
}: ModelSelectProps) {
  const handleChange = (event: SelectChangeEvent<string>) => {
    onChange(event.target.value);
  };

  const labelId = `model-select-${label}`;

  return (
    <FormControl fullWidth size={size} disabled={disabled}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        value={value}
        label={label}
        onChange={handleChange}
      >
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

export type { ModelOption };
```

- [ ] **Step 2: 编写测试**

```js
// apps/web/src/components/model-select.test.mjs
import { describe, it } from 'node:test';
import assert from 'node:assert';

describe('ModelSelect', () => {
  it('should be importable', async () => {
    const { ModelSelect } = await import('./model-select.tsx');
    assert.strictEqual(typeof ModelSelect, 'function');
  });
});
```

- [ ] **Step 3: 运行测试**

Run: `cd apps/web && node --test src/components/model-select.test.mjs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/model-select.tsx apps/web/src/components/model-select.test.mjs
git commit -m "feat(web): 添加 ModelSelect 模型选择组件"
```

---

## Task 17: E2E 测试抽象层

**Files:**
- Create: `apps/web/e2e/selectors.ts`
- Create: `apps/web/e2e/helpers.ts`
- Create: `apps/web/e2e/routes.ts`

- [ ] **Step 1: 创建 routes.ts**

```ts
// apps/web/e2e/routes.ts
export const routes = {
  // 阶段 1 已存在路由
  home: '/',
  chat: '/chat',
  settings: '/settings',
  archive: '/archive',

  // 旧路由（阶段 2 重定向测试用，阶段 1 不引用）
  legacyTask: (id: string) => `/tasks?id=${id}`,
  legacyReview: (id: string) => `/review?id=${id}`,
  legacyResult: (id: string) => `/result?id=${id}`,
  legacyArchiveDetail: (id: string) => `/archive/detail?id=${id}`,
} as const;

// TODO: 阶段 2 启用的新路由
// export const projectRoutes = {
//   newProject: '/new',
//   project: (id: string) => `/p/${id}`,
//   ...
// };
```

- [ ] **Step 2: 创建 selectors.ts**

```ts
// apps/web/e2e/selectors.ts
export const selectors = {
  appHeader: {
    root: '[data-testid="app-header"]',
    searchInput: '[data-testid="global-search-input"]',
    chatLink: '[data-testid="chat-link"]',
    settingsLink: '[data-testid="settings-link"]',
  },
  home: {
    newProjectButton: '[data-testid="new-project-button"]',
    projectCard: '[data-testid="project-card"]',
    viewToggle: '[data-testid="view-toggle"]',
  },
  common: {
    confirmDialog: '[data-testid="confirm-dialog"]',
    confirmButton: '[data-testid="confirm-button"]',
    cancelButton: '[data-testid="cancel-button"]',
    notification: '[data-testid="notification"]',
  },
} as const;

// TODO: 阶段 2 新增选择器
// export const newProjectSelectors = { ... };
// export const workspaceSelectors = { ... };
```

- [ ] **Step 3: 创建 helpers.ts**

```ts
// apps/web/e2e/helpers.ts
import { Page } from '@playwright/test';
import { routes } from './routes';

export async function navigateToHome(page: Page) {
  await page.goto(routes.home);
}

export async function navigateToChat(page: Page) {
  await page.goto(routes.chat);
}

export async function navigateToSettings(page: Page) {
  await page.goto(routes.settings);
}

// TODO: 阶段 2 新增 helpers
// export async function createProject(...) { ... }
// export async function navigateToWorkspace(...) { ... }
```

- [ ] **Step 4: Commit**

```bash
git add apps/web/e2e/selectors.ts apps/web/e2e/helpers.ts apps/web/e2e/routes.ts
git commit -m "test(web): 添加 E2E 测试抽象层（routes/selectors/helpers）"
```

---

## Task 18: 全量测试与验收

**Files:**
- All files created/modified in phase 1

- [ ] **Step 1: 运行前端单元测试**

Run: `cd apps/web && npm test`
Expected: 所有新组件测试 PASS

- [ ] **Step 2: 运行前端构建校验**

Run: `cd apps/web && npm run build`
Expected: 成功，无 TypeScript 错误

- [ ] **Step 3: 运行 ESLint**

Run: `cd apps/web && npm run lint`
Expected: 无新增错误（允许既有警告）

- [ ] **Step 4: 运行 Playwright E2E 测试（仅选择器抽象相关，不跑全量）**

Run: `cd apps/web && npx playwright test chat-settings.spec.ts --reporter=line`
Expected: PASS（验证现有测试不受主题重构影响）

- [ ] **Step 5: 手动验证清单**

- [ ] 首页 `/` 能正常加载，背景色为浅色
- [ ] 使用 Playwright `emulateMedia({ colorScheme: 'dark' })` 访问首页，验证深色模式背景正确
- [ ] 所有新组件能正常 import，无 TypeScript 报错
- [ ] `window.confirm` 未被本阶段替换（页面重构阶段再做）

深色模式 E2E 验证示例：

```ts
import { test, expect } from '@playwright/test';

test('首页支持深色模式', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/');
  const box = await page.locator('[data-testid="root-layout-box"]');
  await expect(box).toHaveCSS('background-color', 'rgb(15, 20, 18)');
});
```

- [ ] **Step 6: 归档 worklog 并提交**

按项目 `CLAUDE.md` 规范，最终提交前需先完成 worklog 归档，并获取用户明确同意。

6.1 获取用户明确同意（如"同意执行"/"同意提交"/"同意"）。

6.2 归档活跃问题文档：

```bash
mv worklog/active/UI优化/20260626-01-UIUX体验重塑设计.md worklog/archive/UI优化/20260626-01-UIUX体验重塑设计.md
```

6.3 更新 `worklog/index.md`（仅保留未完成问题，移除本问题条目）。

6.4 更新 `worklog/history.md`（追加本问题标题、路径、一句话摘要）。

6.5 核对仓库信息：

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

6.6 提交：

```bash
git add .
git commit -m "feat(web): 完成 UI/UX 体验重塑阶段 1 — 设计系统与通用组件层

- 重构 AppThemeProvider，注入 Design Token，支持 light/dark/system 模式
- 新增 10 个通用组件：PageContainer、StageBadge、ProgressBar、EmptyState、LoadingOverlay、SkeletonGrid、ConfirmDialog、NotificationCenter、DecisionBar、ModelSelect
- 清理 globals.css，颜色 Token 迁移到 MUI Theme
- 更新 Root Layout，接入动态背景、metadata 导出与 NotificationProvider
- 建立 E2E 测试抽象层（routes/selectors/helpers）

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>"
```

---

## 验收标准

- [ ] `AppThemeProvider` 支持 light/dark/system 三种模式，`localStorage` 持久化生效。
- [ ] MUI Theme 自定义 Palette 类型扩展通过 TypeScript 编译。
- [ ] `shadows` 数组为完整 25 元素，无 `as any`。
- [ ] `globals.css` 不再包含重复颜色 Token。
- [ ] 10 个通用组件全部创建并有对应测试文件，测试通过。
- [ ] `layout.tsx` 接入 `ThemeModeProvider` 和 `NotificationProvider`；本地字体配置结构已建立但阶段 1 暂不启用。
- [ ] E2E 抽象层（`routes.ts`、`selectors.ts`、`helpers.ts`）已创建。
- [ ] `npm test`、`npm run build`、`npm run lint` 全部通过。
- [ ] 至少一个现有 E2E spec 通过，证明主题重构未破坏现有页面。

---

## 风险与回滚

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| MUI Theme 重构导致现有页面视觉回归 | 中 | 本阶段不改页面结构，仅改主题；阶段 1 结束后跑现有 E2E 验证 |
| `next/font/local` 占位字体文件导致 FOIT | 低 | 使用 `display: swap` 和系统字体回退 |
| 深色模式水合不匹配 | 中 | Layout 使用 `suppressHydrationWarning`，ThemeModeProvider 使用 `noSsr` |
| 新组件与现有组件命名冲突 | 低 | 所有新组件使用清晰前缀，避免与现有 4 个通用组件重名 |

若出现不可控回归，回滚到阶段 1 开始前的 commit：

```bash
git log --oneline -20
# 找到阶段 1 开始前的 commit hash
git reset --hard <commit-hash>
```

---

## 下一阶段依赖

阶段 2（首页 + 项目工作台 + 路由迁移）依赖本阶段完成的：

- `PageContainer`、`StageBadge`、`ProgressBar`、`ModelSelect`
- `ProjectShell`（将基于 `PageContainer` 扩展）
- `StageNav`（将基于 `StageBadge` 扩展）
- `NotificationCenter`（用于操作反馈）
- `ConfirmDialog`（用于高风险操作确认）
- E2E 抽象层（`routes.ts`、`selectors.ts`、`helpers.ts`）
