"use client";

import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";
import DataObjectOutlinedIcon from "@mui/icons-material/DataObjectOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import StorageOutlinedIcon from "@mui/icons-material/StorageOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import Link from "next/link";
import { ReactNode } from "react";
import { Box, Breadcrumbs, Button, Card, CardContent, Chip, Divider, Stack, Typography } from "@mui/material";
import { WorkbenchPageLayout } from "@/components/workbench-page-layout";
import { homeHref, settingsHref, settingsModelsHref, settingsRagHref } from "@/lib/task-routes";

export type SettingsSection = "overview" | "rag" | "models";

/** 与工作台 md 侧栏槽位保持一致，避免导航在中等宽度重复出现在中央顶部。 */
const SETTINGS_NAVIGATION_MIN_WIDTH = 900;

const sectionCopy: Record<SettingsSection, { title: string; description: string; crumb?: string }> = {
  overview: {
    title: "设置中心",
    description: "集中查看语料库状态与模型协议，并进入需要处理的配置。",
  },
  rag: {
    title: "小说 RAG 数据库",
    description: "同步新增资料、查看索引状态，并在必要时安全执行全量重建。",
    crumb: "RAG 数据库",
  },
  models: {
    title: "模型协议配置",
    description: "为 Gateway 模型选择请求协议，确保任务和对话使用正确的兼容层。",
    crumb: "模型协议",
  },
};

const navItems = [
  { section: "overview" as const, label: "设置中心", href: settingsHref(), icon: <SettingsOutlinedIcon fontSize="small" /> },
  { section: "rag" as const, label: "RAG 数据库", href: settingsRagHref(), icon: <StorageOutlinedIcon fontSize="small" /> },
  { section: "models" as const, label: "模型协议", href: settingsModelsHref(), icon: <TuneOutlinedIcon fontSize="small" /> },
];

function SettingsNav({ section }: { section: SettingsSection }) {
  return (
    <Card data-testid="settings-side-navigation" component="nav" aria-label="设置导航" variant="outlined" sx={{ height: "100%", minHeight: 0, boxShadow: "none" }}>
      <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
        <Stack spacing={2.5} sx={{ height: "100%" }}>
          <Stack spacing={0.75}>
            <Stack direction="row" spacing={1} alignItems="center">
              <DataObjectOutlinedIcon color="primary" fontSize="small" aria-hidden="true" />
              <Typography variant="overline" color="text.secondary">创作环境</Typography>
            </Stack>
            <Typography variant="h6">设置</Typography>
            <Typography variant="body2" color="text.secondary">
              先查看状态，再进入单项配置，避免把高风险操作混在同一长页面里。
            </Typography>
          </Stack>

          <Stack spacing={0.75}>
            {navItems.map((item) => (
              <Button
                key={item.section}
                component={Link}
                href={item.href}
                variant={section === item.section ? "contained" : "text"}
                color={section === item.section ? "primary" : "inherit"}
                startIcon={item.icon}
                sx={{ minHeight: 44, justifyContent: "flex-start", px: 1.25 }}
              >
                {item.label}
              </Button>
            ))}
          </Stack>

          <Stack spacing={1} sx={{ mt: "auto" }}>
            <Divider />
            <Button component={Link} href={homeHref()} variant="outlined" startIcon={<ArrowBackRoundedIcon />} sx={{ minHeight: 44, justifyContent: "flex-start" }}>
              返回作品库
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

function MobileSectionLinks({ section }: { section: SettingsSection }) {
  return (
    <Stack
      data-testid="settings-mobile-navigation"
      direction="row"
      spacing={1}
      useFlexGap
      flexWrap="wrap"
      sx={{ display: "flex", [`@media (min-width: ${SETTINGS_NAVIGATION_MIN_WIDTH}px)`]: { display: "none" } }}
    >
      {navItems.map((item) => (
        <Button
          key={item.section}
          component={Link}
          href={item.href}
          size="small"
          variant={section === item.section ? "contained" : "outlined"}
          startIcon={item.icon}
          sx={{ minHeight: 40 }}
        >
          {item.label}
        </Button>
      ))}
    </Stack>
  );
}

export function SettingsShell({ section, children, aside }: { section: SettingsSection; children: ReactNode; aside?: ReactNode }) {
  const copy = sectionCopy[section];
  const header = (
    <Box sx={{ px: { xs: 1.5, sm: 2.5, lg: 3 }, py: { xs: 1.5, sm: 2 } }}>
      <Stack spacing={1.25}>
        <Breadcrumbs aria-label="设置面包屑" separator="›" sx={{ "& .MuiBreadcrumbs-li": { minWidth: 0 } }}>
          <Link href={homeHref()} style={{ color: "inherit", textDecoration: "none" }}>
            <Typography variant="body2" color="text.secondary">首页</Typography>
          </Link>
          {copy.crumb ? (
            <Link href={settingsHref()} style={{ color: "inherit", textDecoration: "none" }}>
              <Typography variant="body2" color="text.secondary">设置</Typography>
            </Link>
          ) : null}
          <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>{copy.crumb ?? "设置"}</Typography>
        </Breadcrumbs>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
          <Stack spacing={0.5} sx={{ minWidth: 0 }}>
            <Typography id="settings-page-title" variant="h4" sx={{ overflowWrap: "anywhere" }}>{copy.title}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ maxWidth: "72ch", overflowWrap: "anywhere" }}>
              {copy.description}
            </Typography>
          </Stack>
          {section !== "overview" ? <Chip size="small" label="设置" color="primary" variant="outlined" sx={{ flexShrink: 0 }} /> : null}
        </Stack>
      </Stack>
    </Box>
  );

  return (
    <WorkbenchPageLayout
      navigation={<SettingsNav section={section} />}
      responsiveSlots={{ navigation: "md" }}
      header={header}
      aside={aside}
      contentLabel={`${copy.title}内容`}
      testId={`settings-${section}-workbench`}
    >
      <Stack spacing={2.5} sx={{ minWidth: 0 }}>
        <MobileSectionLinks section={section} />
        {children}
      </Stack>
    </WorkbenchPageLayout>
  );
}
