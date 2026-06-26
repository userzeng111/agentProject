# AgentProject UI/UX 体验重塑设计

## 1. 概述

### 1.1 背景

AgentProject 是基于 LangChain + LangGraph 的 AI 辅助小说创作系统。前端采用 Next.js 14 App Router + MUI 5 构建。当前 UI 已完成基础功能闭环，但存在以下结构性问题：

- 页面以「任务 task」为核心组织，与用户「创作一部作品」的心理模型不符。
- `task-run-client.tsx`（1783 行）、`task-review-client.tsx`（1744 行）为超大组件，维护困难。
- 样式系统三轨并行：MUI Theme、CSS 变量、`sx` 属性，同一值多处定义。
- 通用组件严重不足，各页面重复实现 Snackbar、Loading、ConfirmDialog。
- 无暗黑模式，夜间使用体验差。
- 页面信息纵向堆叠，用户需要大量滚动才能找到所需模块。

### 1.2 设计目标

将产品从「任务管理器」重新定位为 **「AI 小说创作工坊」**，围绕「作品 project」重构信息架构，让用户始终清楚：

- 自己在为哪一部作品工作；
- 当前处于创作生命周期的哪一阶段；
- 下一步需要做什么决定；
- 高风险操作（模型切换、恢复、取消）的后果是什么。

### 1.3 设计原则

1. **信息分层**：高频信息首屏可见，中频信息锚点/路由可达，低频信息抽屉/子页承载。
2. **状态可视化**：复杂状态通过颜色、图标、进度、流程图共同表达，而非仅靠文字标签。
3. **安全感设计**：高风险操作必须有明确后果说明和二次确认。
4. **锚点跳转优先**：同一阶段内的模块通过锚点一键直达，避免长滚动。
5. **路由跳转分阶段**：不同阶段之间（构思 → 大纲 → 章节 → 审核 → 成书）使用独立路由，每个页面长度可控。
6. **可访问性优先**：所有设计必须满足键盘导航、屏幕阅读器、色彩对比度和减少动画偏好。

### 1.4 术语约定

为降低前后端改造成本，本次重构采用**前端术语升级、后端兼容保留**的策略：

- 前端 UI 和路由使用「作品 project」术语，符合用户心理模型。
- 路由参数 `/p/[projectId]` 实际对应后端的 `task_id`，不强制后端 API 改名。
- 后端 API 仍使用 `/api/tasks/{id}` 等路径，前端在调用时进行映射。
- 如果未来业务扩展需要真正的「项目 → 多任务」关系，再引入后端 `project` 概念。

---

## 2. 设计系统

### 2.1 色彩体系

保留项目已有的「暖色书卷」辨识度，系统化并扩展深色模式。

| Token | Light 模式 | Dark 模式 | 用途 |
|-------|-----------|-----------|------|
| `bg-default` | `#F7EFE2` | `#0F1412` | 页面背景 |
| `bg-paper` | `#FFFAF2` | `#1A211E` | 卡片、面板 |
| `bg-elevated` | `#FFFFFF` | `#242E2A` | 浮层、下拉、对话框 |
| `primary` | `#276451` | `#4FD1A8` | 主按钮、当前阶段、通过状态 |
| `primary-hover` | `#1E4D3E` | `#6EE6C0` | 主按钮悬停 |
| `secondary` | `#9A5F2F` | `#D4A574` | 次要操作、链接 |
| `accent` | `#C49A3B` | `#F5C542` | 强调、星级、重要徽章 |
| `text-primary` | `#1A1612` | `#F2EEE8` | 主要文字 |
| `text-secondary` | `#5C5348` | `#A8A095` | 次要文字 |
| `border` | `#E5D9C8` | `#3A4540` | 分割线、边框 |
| `danger` | `#C0392B` | `#FF6B6B` | 删除、取消、错误 |
| `warning` | `#D68A1E` | `#FFC75F` | 警告、待审核 |

浅色模式像「宣纸 + 松烟墨」，深色模式像「夜间书房」，避免冷色调科技黑。

### 2.2 字体体系

| 角色 | 字体 | 用途 |
|------|------|------|
| Display / 标题 | Source Han Serif CN（思源宋体） | 页面大标题、作品名、章节标题 |
| Body / 正文 | Source Han Sans CN（思源黑体） | UI 标签、按钮、说明文字 |
| Mono / 数据 | JetBrains Mono / SF Mono | 日志、模型名、ID、调试信息 |

**加载方案**：

- 使用 `next/font/local` 加载子集化中文字体包，避免全量加载数 MB 字体文件。
- 字体文件目录：`public/fonts/source-han-serif-cn-subset.woff2`、`public/fonts/source-han-sans-cn-subset.woff2`。
- 子集化工具链：
  - 使用 `fonttools` Python 库或 `subset-font` Node 库按需截取项目所需字符集。
  - 构建脚本：`scripts/subset-fonts.sh`，在 CI 中运行，输出子集化文件到 `public/fonts/`。
  - 如果子集化包构建失败，构建流程不中断，自动降级到系统字体回退栈。
- 系统字体回退栈：
  - 宋体：`font-family: 'Source Han Serif CN', 'Songti SC', 'SimSun', serif`
  - 黑体：`font-family: 'Source Han Sans CN', 'PingFang SC', 'Microsoft YaHei', sans-serif`
- Display 字体仅用于大标题和作品名，UI 标签使用系统黑体以减少加载量。

**`next/font/local` 配置示例**：

```ts
// src/lib/fonts.ts
import localFont from 'next/font/local';

export const sourceHanSerif = localFont({
  src: [
    {
      path: '../../public/fonts/source-han-serif-cn-400-subset.woff2',
      weight: '400',
      style: 'normal',
    },
    {
      path: '../../public/fonts/source-han-serif-cn-600-subset.woff2',
      weight: '600',
      style: 'normal',
    },
  ],
  variable: '--font-serif-sc',
  display: 'swap',
  fallback: ['Songti SC', 'SimSun', 'serif'],
});

export const sourceHanSans = localFont({
  src: [
    {
      path: '../../public/fonts/source-han-sans-cn-400-subset.woff2',
      weight: '400',
      style: 'normal',
    },
    {
      path: '../../public/fonts/source-han-sans-cn-500-subset.woff2',
      weight: '500',
      style: 'normal',
    },
  ],
  variable: '--font-sans-sc',
  display: 'swap',
  fallback: ['PingFang SC', 'Microsoft YaHei', 'sans-serif'],
});
```

```tsx
// src/app/layout.tsx
import { sourceHanSerif, sourceHanSans } from '@/lib/fonts';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${sourceHanSerif.variable} ${sourceHanSans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
```

字号比例：

| Token | 大小 | 行高 | 字重 | 用途 |
|-------|------|------|------|------|
| `display` | 32px | 40px | 600 | 页面主标题 |
| `heading-1` | 24px | 32px | 600 | 区块标题 |
| `heading-2` | 18px | 26px | 500 | 卡片标题 |
| `body` | 14px | 22px | 400 | 正文 |
| `body-sm` | 12px | 18px | 400 | 辅助说明 |
| `caption` | 11px | 16px | 500 | 标签、徽章 |

### 2.3 间距与圆角

统一 4px 基数：

| Token | 值 | 用途 |
|-------|-----|------|
| `radius-sm` | 6px | 按钮、输入框、小标签 |
| `radius-md` | 10px | 卡片、面板 |
| `radius-lg` | 16px | 对话框、大卡片 |
| `radius-xl` | 24px | 首页大卡片、特殊容器 |

间距：`space-1=4px, 2=8px, 3=12px, 4=16px, 5=24px, 6=32px, 7=48px, 8=64px`

### 2.4 阴影与层级

恢复有层次的阴影，不再把 MUI `shadows[1-24]` 全部填成同一个值。

| Token | 值 | 用途 |
|-------|-----|------|
| `shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | 按钮、小标签 |
| `shadow-md` | `0 4px 12px rgba(0,0,0,0.08)` | 卡片悬停 |
| `shadow-lg` | `0 8px 24px rgba(0,0,0,0.12)` | 下拉、浮层 |
| `shadow-xl` | `0 16px 48px rgba(0,0,0,0.16)` | 对话框、模态 |

**MUI 5 集成方式**：

- 通过 `createTheme` 扩展 MUI Theme 的 `palette`、`shadows`、`typography`，将自定义 Token 注入 MUI 体系。
- 示例：`theme.palette.custom.bgDefault` 对应 `#F7EFE2` / `#0F1412`。
- MUI 组件通过 `styleOverrides` 引用 Theme Token，而不是直接写死 CSS 变量。
- 修复当前 `shadows[1-24]` 全部相同值的 bug，仅覆盖需要的索引（1, 2, 4, 8, 16, 24）。

**TypeScript 类型扩展示例**：

```ts
// src/types/mui.d.ts
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

### 2.5 深色模式

- 使用 MUI 5 的 `ThemeProvider` + `createTheme({ palette: { mode: 'dark' } })` 动态切换。
- 主题模式状态通过 React Context 管理，支持：
  - 手动切换（Light / Dark / 跟随系统）。
  - `useMediaQuery('prefers-color-scheme: dark')` 自动检测。
  - `localStorage` 持久化用户选择。
- 深色模式下，CSS 渐变背景替换为深墨绿色系渐变，避免暖色光晕与深色背景产生奇怪混合。

**`system` 模式完整实现**：

```ts
// src/components/theme-mode-provider.tsx
type ThemeMode = 'light' | 'dark' | 'system';

interface ThemeModeContextValue {
  mode: ThemeMode;
  resolvedMode: 'light' | 'dark';
  setMode: (mode: ThemeMode) => void;
}

const ThemeModeContext = createContext<ThemeModeContextValue | null>(null);

export function ThemeModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') return 'system';
    return (localStorage.getItem('theme-mode') as ThemeMode) || 'system';
  });

  const systemPrefersDark = useMediaQuery('(prefers-color-scheme: dark)', { noSsr: true });
  const resolvedMode: 'light' | 'dark' =
    mode === 'system' ? (systemPrefersDark ? 'dark' : 'light') : mode;

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    localStorage.setItem('theme-mode', next);
  }, []);

  return (
    <ThemeModeContext.Provider value={{ mode, resolvedMode, setMode }}>
      {children}
    </ThemeModeContext.Provider>
  );
}
```

优先级规则：用户手动选择 > 系统偏好 > 默认值 `system`。

### 2.6 动画规范

| 类型 | 时长 | 缓动 | 用途 |
|------|------|------|------|
| Micro | 150ms | ease-out | 按钮悬停、颜色变化 |
| Standard | 250ms | cubic-bezier(0.4, 0, 0.2, 1) | 卡片展开、Tab 切换 |
| Emphasis | 400ms | cubic-bezier(0.34, 1.56, 0.64, 1) | 对话框弹出、重要提示 |
| Page | 300ms | ease-in-out | 页面切换、侧边栏展开 |

**实现方式**：

- 优先使用 MUI 内置过渡组件：`Fade`、`Slide`、`Collapse`、`Grow`。
- 简单悬停效果使用 CSS transitions。
- 不引入 Framer Motion 等重型动画库，控制包体积。
- 所有动画响应 `prefers-reduced-motion`。

---

## 3. 信息架构与路由

### 3.1 从「任务视角」到「作品视角」

当前路由围绕 task 平铺，改为围绕 project 组织：

| 新路由 | 对应旧页面 | 说明 |
|--------|-----------|------|
| `/` | `/` | 作品库首页 |
| `/new` | `/create` | 新建作品向导 |
| `/p/[projectId]` | `/tasks` | 项目工作台（运行态）。`projectId` 实际映射后端 `task_id`。 |
| `/p/[projectId]/outline` | `/review` 大纲审核 | 大纲与章节计划 |
| `/p/[projectId]/chapters` | `/review` 章节审核 | 章节管理与批量审核 |
| `/p/[projectId]/review` | `/review` 验证审核 | 综合验证与裁决 |
| `/p/[projectId]/result` | `/result` | 成书阅读器 |
| `/p/[projectId]/archive` | `/archive/detail` | 归档详情（阅读器） |
| `/archive` | `/archive` | 归档库列表 |
| `/chat` | `/chat` | AI 助手（全局独立） |
| `/settings` | `/settings` | 全局设置 |

`/p/` 为 project 缩写，保持 URL 简洁。

### 3.2 动态路由参数获取

- 新路由 `/p/[projectId]` 使用 Next.js App Router 的 `params` 获取参数，而非 `useSearchParams` 读取 `?id=`。
- 页面组件签名：`export default function ProjectPage({ params }: { params: { projectId: string } })`。
- 数据获取逻辑从「客户端读取 query param」改为「服务端/客户端读取 route param」，需要同步更新数据 hook。

### 3.3 导航模式

- **不同阶段之间**：使用路由跳转（如 `/p/[id]/outline` → `/p/[id]/chapters`），每个页面长度可控。
- **同一阶段内的模块**：使用锚点导航（如工作台内的 `#workflow-panel`、`#chapter-list-panel`、`#logs-panel`），点击左侧导航平滑滚动到对应区块。
- **命名约定**：
  - 路由名使用单数或复数名词：`/outline`、`/chapters`、`/review`。
  - 锚点名使用 `-panel` 后缀，避免与路由名冲突：`#chapter-list-panel`（锚点）vs `/chapters`（路由）。
- **左侧阶段导航交互**：
  - 点击阶段名（构思 / 大纲 / 章节 / 审核 / 成书）= 路由跳转到对应页面。
  - 点击「快捷入口」（流程图 / 运行日志 / 调试诊断）= 在当前工作台页面内滚动到对应锚点。
- **快捷入口显示条件**：仅在工作台页面 `/p/[projectId]` 显示。其他阶段页面（outline/chapters/review/result/archive）不显示快捷入口，左侧导航仅保留阶段列表。

---

## 4. 全局布局

### 4.1 布局骨架

```
┌─────────────────────────────────────────────────────────┐
│  AppHeader（固定，高度 56px，玻璃态背景）                    │
├──────────────┬──────────────────────────────┬───────────┤
│              │                              │           │
│  左侧阶段     │        主内容区               │ 右侧抽屉  │
│  锚点导航     │    （固定状态条 + 可滚动内容）  │ （默认隐藏）│
│  （可折叠）   │                              │           │
│              │                              │           │
└──────────────┴──────────────────────────────┴───────────┘
```

- **AppHeader**：左侧 Logo + 当前页面标题，中间全局搜索，右侧通知中心 / AI 助手 / 设置。
- **左侧阶段导航**：仅在作品相关页面出现，显示阶段列表与当前状态，支持路由跳转和锚点滚动。
- **右侧抽屉**：默认完全隐藏，点击「调试 / 参考素材 / 模型详情」时从右侧滑出，不挤压主内容区。

### 4.2 移动端适配

断点与 MUI `theme.breakpoints` 对齐：

- **桌面端（≥1280px）**：三栏，左侧导航展开显示图标+文字。
- **平板端（768px–1279px）**：隐藏右侧抽屉，左侧导航折叠为图标栏，悬停/聚焦时显示 Tooltip 文字提示。
- **手机端（<768px）**：左侧导航变为底部固定 Tab 栏，右侧抽屉变为底部 Sheet。

**响应式状态获取方案**：

- 使用 MUI `useMediaQuery(theme.breakpoints.down('md'))` 检测移动端/平板端。
- 为 SSR 安全，使用 `useMediaQuery` 的 `noSsr` 选项或默认值为桌面端，避免水合不匹配。
- 响应式状态由 `AppLayout` 或 `ProjectShell` 注入到子组件：`isMobile`、`isTablet`、`drawerOpen`。

**移动端底部 Tab 栏结构**：

```
┌─────────────────────────────────────────────────────────┐
│  主内容区                                                │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  [作品库] [工作台] [大纲] [章节] [审核] [成书]           │
└─────────────────────────────────────────────────────────┘
```

- 底部 Tab 栏固定 56px 高度，仅显示图标，当前项高亮。
- 点击 Tab = 路由跳转。
- 快捷入口（调试/日志）放到主内容区右上角的浮动按钮或 AppHeader 菜单中。

**底部 Tab 栏边界行为**：

- **全局页面**（`/chat`、`/settings`、`/archive`）不显示作品相关的底部 Tab 栏。可显示简化导航（作品库 + 设置）或仅保留 AppHeader。
- **未选择作品时**：用户如果直接点击「工作台/大纲/章节/审核/成书」Tab，行为如下：
  - 若存在最近访问的作品 ID（`localStorage` 记录），跳转到该作品的对应页面。
  - 若不存在最近访问作品，跳转到首页 `/`，并引导创建或选择作品。
- **窄屏适配**：375px 宽屏幕下 6 个 Tab 仅显示图标，可横向滚动。当前项用高亮底色和图标颜色区分。

**右侧抽屉在移动端**：

- 使用 MUI `Drawer` 配合 `anchor="bottom"`，以底部 Sheet 形式滑出。
- 高度占屏幕 60%-80%，支持向下滑动手势关闭。

---

## 5. 关键页面结构

### 5.1 首页 / 作品库 `/`

从「双栏任务列表 + 侧边栏统计」改为作品库视角：

- 顶部：搜索栏 + 视图切换（网格/列表）+「新建作品」主按钮。
- 主体：作品卡片网格，每张卡片展示：
  - 封面占位（渐变色块 + 作品名首字）
  - 作品名
  - 当前阶段 Badge
  - 进度条（已完成章节 / 总章节）
  - 最后更新时间
  - 悬停显示快捷操作（继续 / 查看 / 归档）
- 底部：快速操作区（继续最近作品 / 打开 AI 助手 / 进入设置）。
- 空状态：引导创建第一部作品的插图 + 按钮。

### 5.2 新建作品向导 `/new`

从单页长表单改为分步向导：

- 步骤 1：选择小说类型（玄幻 / 仙侠 / 都市 / 悬疑 / 科幻 / 历史 / 言情 / 其他）。
- 步骤 2：输入核心灵感（一句话即可，必填，10-500 字）。
- 步骤 3：确认配置（预计章节数、创作风格、审核严格度、创作模型）。
- 底部固定步骤条：上一步 / 下一步 / 开始创作。

**校验规则表**：

| 字段 | 规则 | 校验时机 | 错误文案 | 按钮状态 |
|------|------|----------|----------|----------|
| 小说类型 | 必须选择一项 | 点击「下一步」时 | 请选择小说类型 | 未选择时「下一步」禁用 |
| 核心灵感 | 必填，10-500 字 | 实时 + 失焦 + 下一步 | 字数不足 10 / 超过 500 / 请输入核心灵感 | 校验失败时「下一步」禁用 |
| 预计章节数 | 必填，1-1000 整数 | 失焦 + 下一步 | 请输入 1-1000 之间的整数 | 校验失败时「开始创作」禁用 |
| 创作风格 | 必须选择一项 | 下一步时 | 请选择创作风格 | 未选择时「开始创作」禁用 |
| 审核严格度 | 必须选择一项 | 下一步时 | 请选择审核严格度 | 未选择时「开始创作」禁用 |
| 创作模型 | 必须选择一项 | 下一步时 | 请选择创作模型 | 未选择时「开始创作」禁用 |

**UI 反馈样式**：

- 使用 MUI `TextField` 的 `error` + `helperText` 属性显示校验错误。
- 步骤条上的步骤图标在校验通过前显示警告图标，通过后显示对勾。

**数据提交方式**：

- 向导数据在客户端临时存储于 `sessionStorage`，用户刷新页面不丢失进度。
- 关闭浏览器后 `sessionStorage` 会丢失，这是可接受的（向导填写时间通常 < 5 分钟）。
- 如果用户需要长期保存草稿，未来可扩展为 `localStorage` 或后端草稿，当前版本不做。
- 最后一步统一提交到现有 `/api/tasks` POST 接口，不修改后端创建契约。
- 如果后端已有字段不支持「小说类型、审核严格度」等，先作为 `metadata` 字段透传，不阻塞前端重构。

**提交失败处理**：

- 如果提交失败，停留在步骤 3，显示错误提示和「重试」按钮。
- 保留用户已填写数据，避免重新输入。
- 网络错误时提供两个选项：
  - 「检查网络后重试」= 重新调用 `/api/tasks` POST。
  - 「返回修改」= 回到步骤 2 且保留数据。
- `sessionStorage` 中的数据在重试期间不会被清空，用户可多次重试。

### 5.3 项目工作台 `/p/[projectId]`

核心页面，采用「固定状态条 + 仪表盘 + 锚点区块」结构。

#### 顶部固定状态条

- 面包屑：作品库 / 《作品名》 / 工作台（可点击返回）。
- 作品名 + 当前阶段 Badge + 进度（16/20 章）。
- 当前动作说明：AI 正在做什么、预计还需多久。
- 主要操作按钮（根据状态动态变化）：继续创作 / 暂停 / 恢复 / 取消。

#### 左侧阶段锚点导航

```
当前阶段（点击 = 路由跳转）
  ○ 构思
  ○ 大纲
  ● 章节  ← 当前
  ○ 审核
  ○ 成书

快捷入口（点击 = 锚点滚动，仅工作台显示）
  [流程图]
  [运行日志]
  [调试诊断]
```

#### 首屏仪表盘

6 张信息卡片网格：

1. **当前阶段**：阶段名、已运行时间、下一步提示。
2. **最近事件**：最近 3 条事件（章节通过、审核中、错误等）。
3. **模型配置**：当前创作模型、审核模型，可点击切换。
4. **章节进度**：进度条 + 已完成/总章节数。
5. **审核状态**：通过 / 打回 / 待审数量统计。
6. **快捷操作**：查看结果、审核当前章、导出大纲。

#### 锚点区块

首屏下方，点击左侧「快捷入口」平滑滚动：

- `#workflow-panel`：流程图区块（固定高度 360px，可缩放）。
- `#chapter-list-panel`：章节列表（表格/卡片混合，支持批量操作）。
- `#review-history-panel`：审核历史时间线。
- `#logs-panel`：运行日志（默认折叠，可展开）。

### 5.4 大纲页 `/p/[projectId]/outline`

- 顶部 Tabs：世界观 / 人物设定 / 章节计划。
- 主体：Markdown 渲染的大纲内容。
- 章节计划按批次展示（每批 10 章），支持分批生成和锁定。
- 操作：保存 / 提交审核。

### 5.5 章节页 `/p/[projectId]/chapters`

- 顶部筛选 Tabs：全部 / 草稿 / 待审 / 已通过 / 打回。
- 主体：章节列表，每行展示章节号、标题、状态、字数、操作。
- 操作：查看、编辑、重新生成、批量选择后批量审核。

### 5.6 审核页 `/p/[projectId]/review`

最重要的决策页面：

- 顶部分类 Tabs：大纲审核 / 章节审核 / 全文验证。
- 主体：左右分屏
  - 左侧：AI 生成的内容（大纲/章节正文，可滚动）。
  - 右侧：审核意见与评分（可滚动，支持逐条展开）。
- 底部固定操作栏：
  - 左侧：次要操作（打回并填写原因 / 暂缓）。
  - 右侧：主要操作（通过，进入下一章）。

### 5.7 结果页 `/p/[projectId]/result`

- 左侧可折叠目录。
- 右侧阅读器样式正文。
- 顶部导出操作：导出 Markdown / PDF / 分享。

### 5.8 归档详情 `/p/[projectId]/archive`

与结果页结构类似，顶部增加作品元信息：创建时间、总字数、使用模型、归档时间。

---

## 6. 通用组件层

### 6.1 新增/重组组件清单

#### 布局类

- `AppLayout`：全局布局骨架。
- `ProjectShell`：作品页面统一外壳。
- `PageContainer`：统一内容区容器。
- `DrawerPanel`：右侧可滑出抽屉。
- `MobileBottomNav`：移动端底部 Tab 栏。
- `MobileSheet`：移动端底部 Sheet。

#### 导航类

- `AppHeader`：顶部导航（重构）。
- `StageNav`：左侧阶段导航（支持路由跳转 + 锚点滚动）。
- `PageBreadcrumb`：自动解析路由的面包屑。
- `ProjectCard`：首页作品卡片。

#### 反馈类

- `EmptyState`：空状态。
- `LoadingOverlay`：加载遮罩。
- `SkeletonGrid`：网格骨架屏。
- `ConfirmDialog`：替代 `window.confirm`。
- `NotificationCenter`：跨页面通知中心。
- `DecisionBar`：底部固定决策操作栏。

#### 内容类

- `MarkdownContent`：统一 Markdown 渲染（重构，支持 article/outline/reader 变体）。
- `StageBadge`：阶段状态徽章。
- `ProgressBar`：统一进度条。
- `LogPanel`：可折叠日志面板。
- `Timeline`：审核历史时间线。

#### 表单类

- `ModelSelect`：模型选择下拉框。
- `Stepper`：分步向导步骤条。
- `FormSection`：表单分组容器。

### 6.2 关键组件行为

#### `StageBadge`

根据状态显示不同样式：

- `running`：绿色 + 脉冲动画点。
- `completed`：绿色 + 对勾图标。
- `waiting`：琥珀色 + 时钟图标。
- `failed`：红色 + 错误图标。
- `paused`：灰色 + 暂停图标。

#### `DecisionBar`

所有需要用户做决定的页面底部统一使用：

```tsx
<DecisionBar
  actions={[
    { label: "打回并填写原因", variant: "outlined", color: "warning", onClick: handleReject },
    { label: "暂缓", variant: "outlined", onClick: handleDefer },
    { label: "通过，进入下一章", variant: "contained", color: "primary", onClick: handleApprove },
  ]}
/>
```

**层级规范**：

- `DecisionBar` 使用 `position: sticky` 或 `fixed`，`z-index: 1150`。
- 明确低于 MUI Snackbar（1400），高于 MUI AppBar（1100），避开 MUI Drawer（1200）。
- 右侧抽屉打开时，`DecisionBar` 仍可见但不与抽屉内容重叠（抽屉使用 `position: fixed` 覆盖在内容区上方）。
- 移动端键盘弹出时，底部栏保持固定（通过 `position: sticky` + `bottom: 0` 避免 iOS Safari viewport 问题）。

#### `NotificationCenter`

替代各页面独立维护的 Snackbar：

- 全局 Context 管理，不引入 Redux。
- 支持 success / error / warning / info 类型。
- 支持常驻和自动消失。
- 桌面端从右上角滑出，移动端从底部滑出。

#### `ErrorFallback`

统一错误边界 UI：

```ts
interface ErrorFallbackProps {
  error?: Error;
  reset?: () => void;
  title?: string;
  description?: string;
  boundary?: 'page' | 'component' | 'global';
}
```

- `boundary="page"`：用于 Next.js App Router `error.tsx`，显示页面级错误。
- `boundary="component"`：用于包裹复杂面板，显示组件级错误。
- `boundary="global"`：用于 `global-error.tsx`，显示根级错误。
- 统一视觉：错误图标 + 标题 + 描述 + 重试按钮。

---

## 7. 交互与动画

### 7.1 导航交互

- **不同阶段之间路由跳转**：页面淡入（fade + slideUp，300ms）。
- **同一阶段内锚点滚动**：左侧导航高亮跟随当前可视区块，滚动 smooth。
- **作品卡片点击**：进入工作台并自动滚动到当前阶段锚点。
- **面包屑**：可点击返回上级，悬停显示完整路径。

### 7.2 工作台交互

- **仪表盘卡片**：悬停轻微上浮 + 阴影加深，点击展开对应详情。
- **锚点区块**：默认全部渲染，但 `#logs-panel` 默认折叠，减少首屏信息密度。
- **右侧抽屉**：从右侧滑入，覆盖主内容区。

### 7.3 审核页交互

- **左右分屏**：两栏独立滚动，右侧意见可单独折叠。
- **评分展开**：点击某项评分，展开详细评语。
- **底部操作栏**：始终固定，主要操作放在右侧，次要操作放在左侧。

### 7.4 状态与反馈

| 状态 | 视觉反馈 | 文案示例 |
|------|----------|----------|
| API 加载中 | Skeleton 骨架屏 + 禁用操作按钮 | 正在加载作品信息… |
| API 失败 | ErrorFallback 组件 + 重试按钮 | 加载失败，请检查网络后重试 |
| 空状态 | EmptyState 插画 + 引导操作 | 还没有章节，点击生成第一章 |
| 操作确认 | ConfirmDialog 弹窗 | 取消后任务将暂停，已生成内容不会丢失，是否继续？ |
| 模型切换 | NotificationCenter 提示 | 模型已切换为 Claude，后续章节将使用新模型 |
| SSE 断连 | StatusBar 显示断连提示 + 自动重连动画 | 连接已断开，正在尝试重连… |

---

## 8. 可访问性与性能

### 8.1 可访问性

- 所有图标按钮带 `aria-label`。
- 表单输入框关联 `label`。
- 颜色对比度满足 WCAG AA：正文 4.5:1，大号文字 3:1。
- 键盘可完整导航所有功能。
- 焦点状态清晰可见（2px 主色轮廓）。
- 语义化 HTML 标签，支持屏幕阅读器。
- 支持 `prefers-reduced-motion` 关闭动画。

### 8.2 性能

- 封面使用 CSS 渐变，避免真实图片加载。
- 大组件拆分为独立文件，配合 Next.js 动态导入。
- Markdown 渲染按需加载。
- 动画使用 `transform` 和 `opacity`，不触发重排。
- 列表使用稳定 `key`。
- 中文字体使用子集化或系统字体回退，避免全量加载。

---

## 9. 实施阶段与工期估算

建议分 4 个阶段落地，每阶段末尾同步更新测试。总工期约 6-8 周。

### 阶段 1：设计系统 + 通用组件层 + 深色模式基础（1.5-2 周）

- 重构 `AppThemeProvider`，统一 Design Token，修复 `shadows` 数组 bug。
- 实现 Theme `mode` 切换机制与 `localStorage` 持久化。
- 清理 `globals.css` 与 MUI Theme 重复定义。
- 新增通用组件：`PageContainer`、`StageBadge`、`ProgressBar`、`ConfirmDialog`、`NotificationCenter`、`DecisionBar`、`EmptyState`、`LoadingOverlay`、`SkeletonGrid`、`ModelSelect`。
- **E2E 测试同步**：
  - 技术栈：Playwright（现有 `apps/web/e2e/`）。
  - 将硬编码 URL 和按钮文本提取到 `e2e/selectors.ts` 和 `e2e/helpers.ts`。
  - 现有测试文件：`chat-settings.spec.ts`、`task-state-branches.spec.ts` 等 10+ 个 spec。
- **验收**：现有页面在不改结构的情况下应用新主题，无视觉回归；新组件单元测试通过；深色模式基础架构可用。

### 阶段 2：首页 + 项目工作台 + 路由迁移（2-2.5 周）

- 首页改为作品卡片网格。
- 新增 `ProjectShell`、`StageNav`、锚点滚动。
- 重构工作台为固定状态条 + 仪表盘 + 锚点区块。
- 迁移 `/tasks` 到 `/p/[projectId]`，`/create` 到 `/new`，旧路由保留 302 重定向。
- 实现移动端基础布局（底部 Tab 栏、图标栏折叠）。
- **深色模式验证**：首页和工作台在深浅两种模式下均通过对比度检查。
- **E2E 测试同步**：更新核心路径测试到新路由和 UI 文本。
- **验收**：作品库 → 工作台路径完整可用，新旧路由重定向生效，E2E 测试全通过。

### 阶段 3：审核页 + 结果页 + 章节页 + 大组件拆分（2-2.5 周）

- 审核页改为左右分屏 + 底部固定操作栏。
- 结果页改为阅读器布局。
- 章节页增加批量审核。
- 拆分 `task-run-client.tsx` 和 `task-review-client.tsx`（详见附录 A）。
- **深色模式验证**：审核页、结果页、章节页在深浅两种模式下均通过对比度检查。
- **E2E 测试同步**：补充审核页、结果页、章节页的 E2E 测试。
- **验收**：复杂决策和阅读场景完整可用，大组件拆分后每个文件 <= 300 行。

### 阶段 4：深色模式精调 + 移动端适配 + 动画打磨 + 可访问性审计（1-1.5 周）

- 深色模式下全站颜色精调与对比度检查（使用 axe-core 或 Lighthouse）。
- 移动端布局精调（底部 Sheet、手势关闭、键盘适配）。
- 全局动画与微交互统一打磨。
- 可访问性审计与修复。
- **E2E 测试同步**：补充移动端 E2E 测试与可访问性自动化检查。
- **验收**：深色模式完整覆盖，移动端主要流程可用，Lighthouse a11y >= 95。

---

## 10. 风险与回滚策略

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 路由变更影响现有 E2E 测试 | 高 | 阶段 1 抽象硬编码选择器，阶段 2 同步更新测试，旧路由保留 302 重定向 |
| MUI Theme 重构导致视觉回归 | 中 | 阶段 1 小范围验证，保留旧主题备份分支 |
| 大组件拆分引入状态管理 bug | 中 | 拆分前定义边界（附录 A），补充单元测试，保持 props 接口稳定 |
| 深色模式覆盖不全 | 低 | 每个阶段都进行深色模式验证，阶段 4 做全局精调 |
| 移动端适配改动面大 | 中 | 阶段 1 预留响应式接口，阶段 2 同步做基础适配 |
| 字体子集化构建失败 | 低 | 自动降级到系统字体回退栈，不中断构建 |

若出现不可控回归，可从 `uxuiFix` 分支切出回滚分支，逐阶段回退。

---

## 11. 验收标准

- [ ] 所有页面应用统一 Design Token，无 MUI Theme / CSS 变量 / `sx` 三轨并存。
- [ ] 首页、工作台、审核页完成体验重塑，用户可在首屏找到关键信息。
- [ ] 工作台支持左侧锚点导航跳转，无需长滚动。
- [ ] 不同阶段之间使用独立路由，每个页面长度可控。
- [ ] 通用组件层覆盖 Loading、Empty、Confirm、Notification、DecisionBar。
- [ ] 支持浅色/深色模式切换与 `localStorage` 持久化。
- [ ] 前端单元测试与 E2E 测试全部通过。
- [ ] 通过键盘可完整操作主要流程。
- [ ] 所有交互元素对比度满足 WCAG AA（正文 >= 4.5:1）。
- [ ] `task-run-client.tsx` 和 `task-review-client.tsx` 拆分后每个文件 <= 300 行。
- [ ] Lighthouse 性能评分 >= 90，可访问性评分 >= 95。
- [ ] 深色模式下所有颜色对比度 >= 4.5:1。
- [ ] 移动端主要流程可用（首页、工作台、审核页）。

---

## 附录 A：大组件拆分方案

### A.1 `task-run-client.tsx` 拆分

**现有文件**：`src/features/task-run/task-run-client.tsx`（1783 行）

**拆分后结构**：

```
src/features/task-run/
├── task-run-client.tsx          # 容器组件（<= 200 行）
├── status-bar.tsx               # 顶部固定状态条
├── dashboard-grid.tsx           # 首屏仪表盘 6 张卡片
├── workflow-panel.tsx           # 流程图锚点区块
├── chapter-list-panel.tsx       # 章节列表锚点区块
├── review-history-panel.tsx     # 审核历史锚点区块
├── log-panel.tsx                # 运行日志锚点区块
├── use-workspace.ts             # 工作台数据 hook
└── use-project-events.ts        # SSE/事件消费 hook
```

**容器组件 `task-run-client.tsx` 职责**：

- 通过 `params.projectId` 获取当前作品 ID。
- 调用 `useWorkspace(projectId)` 获取作品数据、当前阶段、进度、事件等。
- 调用 `useProjectEvents(projectId)` 消费 SSE 实时事件。
- 维护顶层 UI 状态：`drawerOpen`、`activeAnchor`。
- 组合 `ProjectShell`、`StatusBar`、`DashboardGrid`、各 Panel 组件。

**各子组件 props 接口**：

```ts
// status-bar.tsx
interface StatusBarProps {
  project: Project;
  currentStage: Stage;
  progress: { completed: number; total: number };
  currentAction?: string;
  primaryAction: { label: string; onClick: () => void; disabled?: boolean };
  secondaryActions?: Array<{ label: string; onClick: () => void }>;
}

// dashboard-grid.tsx
interface DashboardGridProps {
  project: Project;
  currentStage: Stage;
  progress: { completed: number; total: number };
  recentEvents: ProjectEvent[];
  modelConfig: { writer: string; reviewer: string };
  reviewStats: { approved: number; rejected: number; pending: number };
  onContinue: () => void;
  onReview: () => void;
  onExportOutline: () => void;
  onSwitchModel: () => void;
}

// workflow-panel.tsx
interface WorkflowPanelProps {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  currentNodeId?: string;
  height?: number;
}

// chapter-list-panel.tsx
interface ChapterListPanelProps {
  chapters: Chapter[];
  selectedChapterIds: string[];
  onSelect: (ids: string[]) => void;
  onView: (id: string) => void;
  onEdit: (id: string) => void;
  onRegenerate: (ids: string[]) => void;
  onBatchReview: (ids: string[]) => void;
}

// review-history-panel.tsx
interface ReviewHistoryPanelProps {
  history: ReviewHistoryItem[];
  onItemClick?: (item: ReviewHistoryItem) => void;
}

// log-panel.tsx
interface LogPanelProps {
  logs: LogEntry[];
  defaultExpanded?: boolean;
  filters?: { level?: LogLevel[]; search?: string };
}
```

**状态管理策略**：

- 容器组件持有顶层状态（`projectId`、当前阶段、抽屉开关、锚点高亮）。
- 各面板组件通过 props 接收数据，内部维护局部 UI 状态（展开/折叠、筛选条件、选中项）。
- SSE 事件统一在 `use-project-events.ts` 中消费，通过回调或 props 更新 `useWorkspace` 返回的数据。
- 不引入 Redux/Zustand，使用 React Context 仅用于 `NotificationCenter`、主题模式等真正需要全局共享的状态。

### A.2 `task-review-client.tsx` 拆分

**现有文件**：`src/features/task-review/task-review-client.tsx`（1744 行）

**拆分后结构**：

```
src/features/task-review/
├── task-review-client.tsx       # 容器组件（<= 200 行）
├── review-layout.tsx            # 左右分屏布局
├── review-content.tsx           # 左侧 AI 生成内容
├── review-sidebar.tsx           # 右侧审核意见
├── review-scores.tsx            # 评分展开组件
├── review-tabs.tsx              # 顶部分类 Tabs
├── use-review.ts                # 审核数据 hook
└── use-review-actions.ts        # 通过/打回/暂缓操作 hook
```

**容器组件 `task-review-client.tsx` 职责**：

- 通过 `params.projectId` 获取当前作品 ID。
- 调用 `useReview(projectId, reviewType)` 获取审核对象和审核结果。
- 调用 `useReviewActions(projectId)` 执行通过/打回/暂缓操作。
- 维护当前审核类型（outline/chapter/fulltext）和评分展开状态。
- 组合 `ProjectShell`、`ReviewTabs`、`ReviewLayout`、`DecisionBar`。

**各子组件 props 接口**：

```ts
// review-layout.tsx
interface ReviewLayoutProps {
  reviewType: 'outline' | 'chapter' | 'fulltext';
  content: string;
  reviewResult: ReviewResult;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onDefer: () => void;
  loading?: boolean;
}

// review-content.tsx
interface ReviewContentProps {
  content: string;
  reviewType: 'outline' | 'chapter' | 'fulltext';
  scrollable?: boolean;
}

// review-sidebar.tsx
interface ReviewSidebarProps {
  reviewResult: ReviewResult;
  expandedScoreIds: string[];
  onToggleScore: (id: string) => void;
}

// review-scores.tsx
interface ReviewScoresProps {
  scores: ReviewScore[];
  expandedIds: string[];
  onToggle: (id: string) => void;
}

// review-tabs.tsx
interface ReviewTabsProps {
  activeType: 'outline' | 'chapter' | 'fulltext';
  onChange: (type: 'outline' | 'chapter' | 'fulltext') => void;
}
```

**状态管理策略**：

- 容器组件管理当前审核对象（大纲/章节/全文）和审核动作结果。
- 左右分屏组件通过容器高度和 `overflow: auto` 实现独立滚动。
- 评分展开状态由 `review-sidebar.tsx` 自行维护，或通过 `expandedScoreIds` + `onToggleScore` 受控。
- 操作结果通过 `NotificationCenter` 全局提示。

---

## 附录 B：路由与术语变更影响评估

### B.1 前后端术语映射

| 前端术语 | 后端术语 | 说明 |
|----------|----------|------|
| 作品 project | 任务 task | 前端路由和 UI 使用 project，API 调用使用 task_id |
| 作品 ID projectId | 任务 ID taskId | `/p/[projectId]` 中的 `projectId` 即后端 `task_id` |
| 创作阶段 stage | 任务状态 status | 前端将后端 status 映射为更友好的阶段名称 |

### B.2 受影响的现有 URL

| 旧 URL | 新 URL | 是否需要重定向 |
|--------|--------|----------------|
| `/create` | `/new` | 是，保留 302 重定向 |
| `/tasks?id=xxx` | `/p/xxx` | 是，保留 302 重定向 |
| `/review?id=xxx` | `/p/xxx/review` | 是，保留 302 重定向 |
| `/result?id=xxx` | `/p/xxx/result` | 是，保留 302 重定向 |
| `/archive/detail?id=xxx` | `/p/xxx/archive` | 是，保留 302 重定向 |

### B.3 后端 API 影响

- 本次重构不修改后端 API 路径和字段名。
- 前端在 API 调用层做术语映射（如 `useProject` hook 内部调用 `/api/tasks/{projectId}`）。
- 如果未来需要真正的「项目 → 多任务」关系，再引入后端 `project` 概念。

---

## 附录 C：状态设计补充

### C.1 全局状态

| 状态 | 管理方式 | 说明 |
|------|----------|------|
| 主题模式 | React Context + localStorage | light / dark / system |
| 通知消息 | React Context | NotificationCenter |
| 当前作品上下文 | URL params + 数据 hook | 不存全局状态 |

### C.2 页面级状态

| 页面 | 关键状态 | 说明 |
|------|----------|------|
| 工作台 | 当前阶段、抽屉开关、锚点高亮 | 容器组件持有 |
| 审核页 | 当前审核对象、评分展开、操作结果 | 容器组件持有 |
| 新建向导 | 步骤、表单数据 | sessionStorage + 容器组件 |

### C.3 错误与空状态

| 场景 | 组件 | 文案示例 |
|------|------|----------|
| 首页无作品 | EmptyState | 还没有作品，点击创建第一部小说 |
| 章节列表为空 | EmptyState | 还没有章节，点击生成第一章 |
| 审核历史为空 | EmptyState | 暂无审核记录 |
| API 失败 | ErrorFallback | 加载失败，请检查网络后重试 |
| SSE 断连 | StatusBar | 连接已断开，正在尝试重连… |

### C.4 错误边界层级

- **页面级错误边界**：使用 Next.js App Router 的 `error.tsx`，内部渲染 `<ErrorFallback error={error} reset={reset} boundary="page" />`。
- **组件级错误边界**：使用 `react-error-boundary` 或自定义 Error Boundary 类组件包裹复杂面板（如流程图、审核意见），失败时渲染 `<ErrorFallback boundary="component" reset={reset} />`。
- **全局错误边界**：`global-error.tsx` 捕获根布局错误，渲染 `<ErrorFallback boundary="global" />`，视觉样式与 `ErrorFallback` 保持一致。
- **错误上报**：当前版本仅记录到控制台，未来可接入 Sentry 等监控服务。

---

## 附录 D：SEO 与国际化策略

### D.1 SEO

- 使用 Next.js 14 `generateMetadata` 为每个页面生成标题和描述。
- 动态路由 `/p/[projectId]` 的标题模板：`《{作品名}》| 小说工坊`。
- 静态页面标题：
  - 首页：`我的作品 | 小说工坊`
  - 新建：`新建作品 | 小说工坊`
  - 设置：`设置 | 小说工坊`
- Open Graph：
  - `og:title` 与页面标题一致。
  - `og:description` 使用作品简介（动态路由）或固定站点描述（静态页面）。
  - `og:image` 使用静态占位图（如 `public/og-default.png`），动态路由可后续扩展为按作品生成。
- Twitter Card：与 Open Graph 保持一致。

**`generateMetadata` 示例**：

```ts
// src/app/p/[projectId]/page.tsx
import { getProject } from '@/lib/api';

export async function generateMetadata({ params }: { params: { projectId: string } }) {
  const project = await getProject(params.projectId);
  return {
    title: project ? `《${project.name}》| 小说工坊` : '作品 | 小说工坊',
    openGraph: {
      title: project ? `《${project.name}》| 小说工坊` : '作品 | 小说工坊',
      description: project?.synopsis || 'AI 辅助小说创作',
      images: ['/og-default.png'],
    },
  };
}
```

### D.2 国际化

- 当前版本仅支持中文。
- 所有 UI 文案抽离到 `src/lib/messages.ts`，采用嵌套命名空间结构。
- **命名空间约定**：最大嵌套深度 3 层，格式为 `page.section.element`。
- **动态插值**：当前使用模板字符串函数，未来迁移到 `next-intl` 时替换为 `t('key', { param })` 格式。

```ts
// src/lib/messages.ts
export const messages = {
  home: {
    title: '我的作品',
    emptyTitle: '还没有作品',
    emptyAction: '创建第一部小说',
  },
  workspace: {
    title: '工作台',
    continue: '继续创作',
    pause: '暂停',
  },
  review: {
    title: '审核',
    approve: '通过，进入下一章',
    reject: '打回并填写原因',
  },
  project: {
    title: (name: string) => `《${name}》| 小说工坊`,
  },
} as const;
```

---

## 附录 E：E2E 测试同步策略

### E.1 技术栈

- 使用现有 Playwright（`@playwright/test` ^1.61.1）。
- 测试目录：`apps/web/e2e/`。
- 现有 spec 文件约 10 个，包括 `chat-settings.spec.ts`、`task-state-branches.spec.ts` 等。

### E.2 阶段 1 输出物

- `e2e/selectors.ts`：集中管理页面元素选择器（data-testid、按钮文本等）。
- `e2e/helpers.ts`：集中管理通用操作（创建作品、导航到工作台等）。
- `e2e/routes.ts`：集中管理 URL 模板，支持新旧路由切换。

### E.3 现有 Spec 迁移清单

| 旧 Spec 文件 | 新 Spec 文件 | 变更类型 | 说明 |
|-------------|-------------|----------|------|
| `chat-settings.spec.ts` | `chat-settings.spec.ts` | 更新 | 更新选择器，路由 `/chat` 不变 |
| `task-state-branches.spec.ts` | `project-state-branches.spec.ts` | 重写 | 从 `/tasks?id=` 改为 `/p/{id}` |
| `task-lifecycle.spec.ts` | `project-lifecycle.spec.ts` | 重写 | 覆盖首页 → 新建 → 工作台完整流程 |
| `review-flow.spec.ts` | `review-flow.spec.ts` | 更新 | 更新审核页 URL 和选择器 |
| `archive-detail.spec.ts` | `project-archive.spec.ts` | 更新 | 从 `/archive/detail?id=` 改为 `/p/{id}/archive` |
| `mobile-layout.spec.ts` | `mobile-layout.spec.ts` | 新增 | 验证移动端底部 Tab 和 Sheet |
| `dark-mode.spec.ts` | `dark-mode.spec.ts` | 新增 | 验证主题切换与持久化 |

### E.4 新增核心用例

1. **作品库 → 新建向导 → 工作台**
   - 访问首页 `/`
   - 点击「新建作品」
   - 完成 3 步向导
   - 验证跳转至 `/p/{id}` 工作台
   - 验证仪表盘显示当前阶段

2. **工作台锚点导航**
   - 进入 `/p/{id}`
   - 点击左侧「流程图」快捷入口
   - 验证主内容区滚动到 `#workflow-panel`
   - 点击「章节列表」快捷入口
   - 验证滚动到 `#chapter-list-panel`

3. **审核页通过/打回流程**
   - 进入 `/p/{id}/review`
   - 验证左右分屏布局
   - 点击评分展开详细意见
   - 点击「通过」并验证状态更新
   - 点击「打回」填写原因并验证

### E.5 路由过渡期策略

- **阶段 2 开始**：所有新功能测试只针对新路由 `/p/{id}`。
- **旧路由 302 重定向**：通过单元测试或单独的 `legacy-routes.spec.ts` 验证 `/tasks?id=xxx` 能正确 302 到 `/p/xxx`。
- **过渡期**：旧 E2E 测试在阶段 1 完成选择器抽象后，阶段 2 一次性迁移到新路由，不双写两套测试。

### E.6 响应式测试

- 在 `playwright.config.ts` 中定义 `desktop` 和 `mobile` 两个 project：
  - `desktop`：viewport 1280x720
  - `mobile`：viewport 375x667，touch 事件启用
- 深色模式测试使用 Playwright 的 `emulateMedia({ colorScheme: 'dark' })`。

---

## 附录 F：MUI 5 Theme 扩展示例

```ts
// src/components/app-theme-provider.tsx
import { createTheme, ThemeProvider } from '@mui/material/styles';
import { useMemo, useState, useCallback, createContext, useContext } from 'react';
import useMediaQuery from '@mui/material/useMediaQuery';

type ThemeMode = 'light' | 'dark' | 'system';

interface ThemeModeContextValue {
  mode: ThemeMode;
  resolvedMode: 'light' | 'dark';
  setMode: (mode: ThemeMode) => void;
}

const ThemeModeContext = createContext<ThemeModeContextValue | null>(null);

const getDesignTokens = (mode: 'light' | 'dark') => ({
  palette: {
    mode,
    primary: { main: mode === 'light' ? '#276451' : '#4FD1A8' },
    secondary: { main: mode === 'light' ? '#9A5F2F' : '#D4A574' },
    background: {
      default: mode === 'light' ? '#F7EFE2' : '#0F1412',
      paper: mode === 'light' ? '#FFFAF2' : '#1A211E',
    },
    text: {
      primary: mode === 'light' ? '#1A1612' : '#F2EEE8',
      secondary: mode === 'light' ? '#5C5348' : '#A8A095',
    },
    custom: {
      bgDefault: mode === 'light' ? '#F7EFE2' : '#0F1412',
      bgPaper: mode === 'light' ? '#FFFAF2' : '#1A211E',
      bgElevated: mode === 'light' ? '#FFFFFF' : '#242E2A',
      textPrimary: mode === 'light' ? '#1A1612' : '#F2EEE8',
      textSecondary: mode === 'light' ? '#5C5348' : '#A8A095',
      border: mode === 'light' ? '#E5D9C8' : '#3A4540',
    },
  },
  shape: { borderRadius: 10 },
  shadows: [
    'none',
    '0 1px 2px rgba(0,0,0,0.05)',
    '0 2px 4px rgba(0,0,0,0.06)',
    '0 3px 6px rgba(0,0,0,0.07)',
    '0 4px 12px rgba(0,0,0,0.08)',
    '0 5px 14px rgba(0,0,0,0.09)',
    '0 6px 16px rgba(0,0,0,0.10)',
    '0 7px 18px rgba(0,0,0,0.11)',
    '0 8px 24px rgba(0,0,0,0.12)',
    '0 9px 26px rgba(0,0,0,0.12)',
    '0 10px 28px rgba(0,0,0,0.12)',
    '0 11px 30px rgba(0,0,0,0.12)',
    '0 12px 32px rgba(0,0,0,0.12)',
    '0 13px 34px rgba(0,0,0,0.12)',
    '0 14px 36px rgba(0,0,0,0.12)',
    '0 15px 38px rgba(0,0,0,0.12)',
    '0 16px 48px rgba(0,0,0,0.16)',
    '0 17px 50px rgba(0,0,0,0.16)',
    '0 18px 52px rgba(0,0,0,0.16)',
    '0 19px 54px rgba(0,0,0,0.16)',
    '0 20px 56px rgba(0,0,0,0.16)',
    '0 21px 58px rgba(0,0,0,0.16)',
    '0 22px 60px rgba(0,0,0,0.16)',
    '0 23px 62px rgba(0,0,0,0.16)',
    '0 24px 64px rgba(0,0,0,0.16)',
  ],
});

export function AppThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') return 'system';
    return (localStorage.getItem('theme-mode') as ThemeMode) || 'system';
  });

  const systemPrefersDark = useMediaQuery('(prefers-color-scheme: dark)', { noSsr: true });
  const resolvedMode: 'light' | 'dark' =
    mode === 'system' ? (systemPrefersDark ? 'dark' : 'light') : mode;

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    localStorage.setItem('theme-mode', next);
  }, []);

  const theme = useMemo(() => createTheme(getDesignTokens(resolvedMode)), [resolvedMode]);

  return (
    <ThemeModeContext.Provider value={{ mode, resolvedMode, setMode }}>
      <ThemeProvider theme={theme}>
        {children}
      </ThemeProvider>
    </ThemeModeContext.Provider>
  );
}

export function useThemeMode() {
  const ctx = useContext(ThemeModeContext);
  if (!ctx) throw new Error('useThemeMode must be used within AppThemeProvider');
  return ctx;
}
```

---

*文档版本：v1.3*
*最后更新：2026-06-26*
