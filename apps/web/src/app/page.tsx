"use client";

import AutoStoriesRoundedIcon from "@mui/icons-material/AutoStoriesRounded";
import ArchiveRoundedIcon from "@mui/icons-material/ArchiveRounded";
import HubRoundedIcon from "@mui/icons-material/HubRounded";
import LayersRoundedIcon from "@mui/icons-material/LayersRounded";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Grid,
  Pagination,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { getDashboard } from "@/lib/api";
import { DashboardResponse, TaskCardSummary, TaskStatus } from "@/lib/types";

const statusLabelMap: Record<TaskStatus, string> = {
  created: "待启动",
  sources_ingested: "已入库",
  planning: "规划中",
  waiting_outline_review: "待审核",
  drafting: "正文生成中",
  waiting_manual_action: "待人工处理",
  assembling: "结果整理中",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
};

function resolveTaskHref(task: TaskCardSummary) {
  if (task.storage_state === "archive") {
    return `/archive/${task.task_id}`;
  }
  if (task.status === "waiting_outline_review") {
    return `/review/${task.task_id}`;
  }
  if (task.status === "completed") {
    return `/result/${task.task_id}`;
  }
  return `/tasks/${task.task_id}`;
}

// 紧凑任务卡片
function TaskListItem({ task }: { task: TaskCardSummary }) {
  return (
    <Card
      variant="outlined"
      sx={{ borderRadius: 3, transition: "all 0.2s", "&:hover": { borderColor: "primary.main" } }}
    >
      <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
        <Stack spacing={1}>
          <Stack
            direction="row"
            spacing={1}
            justifyContent="space-between"
            alignItems="center"
          >
            <Typography
              variant="subtitle1"
              sx={{ fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {task.title || task.task_id}
            </Typography>
            <Chip
              label={statusLabelMap[task.status] ?? task.status}
              size="small"
              sx={{ flexShrink: 0 }}
            />
            <Button
              component={Link}
              href={resolveTaskHref(task)}
              size="small"
              sx={{ flexShrink: 0, minWidth: "auto", px: 1 }}
            >
              查看
            </Button>
          </Stack>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {task.summary}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {task.current_stage} · {task.mode} · {new Date(task.updated_at).toLocaleString()}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  );
}

// Tab 分组 + 前端分页
const PAGE_SIZE = 5;

function TaskTabPanel({ dashboard }: { dashboard: DashboardResponse }) {
  const [activeTab, setActiveTab] = useState(0);
  const [page, setPage] = useState(1);

  const tabConfig = [
    { label: "待处理", total: dashboard.continue_tasks.length, list: dashboard.continue_tasks },
    { label: "运行中", total: dashboard.running_tasks.length, list: dashboard.running_tasks },
    { label: "失败", total: dashboard.failed_tasks.length, list: dashboard.failed_tasks },
  ];

  const current = tabConfig[activeTab];
  const totalPages = Math.max(1, Math.ceil(current.total / PAGE_SIZE));
  const pagedList = current.list.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
    setPage(1);
  };

  const emptyTexts = ["当前没有需要人工继续处理的任务。", "当前没有运行中的任务。", "当前没有失败任务。"];

  return (
    <Card sx={{ borderRadius: 4 }}>
      <Box sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Tabs
          value={activeTab}
          onChange={handleTabChange}
          sx={{
            minHeight: 48,
            "& .MuiTab-root": { minHeight: 48, textTransform: "none", fontWeight: 500 },
          }}
        >
          {tabConfig.map((tab) => (
            <Tab key={tab.label} label={`${tab.label} (${tab.total})`} />
          ))}
        </Tabs>
      </Box>
      <Box sx={{ p: 2 }}>
        {pagedList.length ? (
          <Stack spacing={1.5}>
            {pagedList.map((task) => (
              <TaskListItem key={task.task_id} task={task} />
            ))}
          </Stack>
        ) : (
          <Typography color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
            {emptyTexts[activeTab]}
          </Typography>
        )}
        {current.total > PAGE_SIZE && (
          <Box sx={{ display: "flex", justifyContent: "center", mt: 2 }}>
            <Pagination
              count={totalPages}
              page={page}
              onChange={(_, p) => setPage(p)}
              size="small"
              shape="rounded"
            />
          </Box>
        )}
      </Box>
    </Card>
  );
}

// 侧边栏 - 统计卡片
function SidebarStats({ dashboard }: { dashboard: DashboardResponse }) {
  const stats = [
    { label: "活动运行", value: dashboard.running_tasks.length, sub: `${dashboard.system_summary?.active_runs ?? 0} 接口统计` },
    { label: "归档任务", value: dashboard.system_summary?.archived_runs ?? 0, sub: "已归档运行数" },
    { label: "默认模型", value: dashboard.model_summary?.default_model ?? "未提供", sub: `支持 ${dashboard.model_summary?.supported_models?.length ?? 0} 个` },
  ];

  return (
    <Stack spacing={2}>
      {stats.map((item) => (
        <Card key={item.label}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Stack spacing={0.5}>
              <Typography variant="overline" color="text.secondary">
                {item.label}
              </Typography>
              <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)", wordBreak: "break-all" }}>
                {item.value}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {item.sub}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}

// 侧边栏 - 功能特性
function SidebarFeatures() {
  const features = [
    { icon: <ArchiveRoundedIcon />, title: "归档回查", text: "已完成任务自动归档，随时回看结果与章节。" },
    { icon: <HubRoundedIcon />, title: "先规划后写作", text: "大纲审核机制，把控故事走向后再生成正文。" },
    { icon: <LayersRoundedIcon />, title: "多种创作模式", text: "短篇、长篇、同人创作、风格复刻，灵活选择。" },
    { icon: <AutoStoriesRoundedIcon />, title: "参考文本", text: "上传文本作为世界观或风格参考，融入创作。" },
  ];

  return (
    <Stack spacing={1.5}>
      {features.map((item) => (
        <Card key={item.title} className="glass-card">
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Stack direction="row" spacing={1.5} alignItems="flex-start">
              <Box
                sx={{
                  width: 36,
                  height: 36,
                  borderRadius: 2,
                  display: "grid",
                  placeItems: "center",
                  backgroundColor: "rgba(39, 100, 81, 0.10)",
                  color: "primary.main",
                  flexShrink: 0,
                }}
              >
                {item.icon}
              </Box>
              <Stack spacing={0.5}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                  {item.title}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {item.text}
                </Typography>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ))}
    </Stack>
  );
}

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getDashboard()
      .then((response) => {
        setDashboard(response);
        setError("");
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "读取首页聚合数据失败");
      });
  }, []);

  return (
    <Container maxWidth="lg" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
      <Stack spacing={3} className="page-fade-in">
        {/* 紧凑标题栏 */}
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", sm: "center" }}
        >
          <Stack spacing={1} direction="row" alignItems="baseline" sx={{ flexWrap: "wrap", gap: 1 }}>
            <Typography
              variant="h4"
              sx={{ fontFamily: "var(--font-serif-sc)", lineHeight: 1.2 }}
            >
              小说工坊
            </Typography>
            <Chip label="LangChain + LangGraph + GPT-5.4" size="small" />
            <Typography variant="body2" color="text.secondary" sx={{ width: "100%" }}>
              从灵感到成稿，AI 辅助小说创作。输入创意，审核大纲，生成初稿。
            </Typography>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ flexShrink: 0 }}>
            <Button component={Link} href="/create" size="large" variant="contained">
              创建任务
            </Button>
            <Button component={Link} href="/archive" size="large" variant="outlined">
              归档
            </Button>
          </Stack>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        {dashboard ? (
          <Grid container spacing={3}>
            {/* 主内容区 */}
            <Grid item xs={12} md={8}>
              <TaskTabPanel dashboard={dashboard} />
            </Grid>

            {/* 侧边栏 */}
            <Grid item xs={12} md={4}>
              <Stack spacing={2}>
                <SidebarStats dashboard={dashboard} />
                <Typography variant="overline" color="text.secondary">
                  功能特性
                </Typography>
                <SidebarFeatures />
              </Stack>
            </Grid>
          </Grid>
        ) : (
          /* 骨架屏 */
          <Grid container spacing={3}>
            <Grid item xs={12} md={8}>
              <Card>
                <CardContent>
                  <Stack spacing={2}>
                    <Box sx={{ height: 48, bgcolor: "action.hover", borderRadius: 1 }} />
                    {[1, 2, 3].map((i) => (
                      <Box key={i} sx={{ height: 80, bgcolor: "action.hover", borderRadius: 2 }} />
                    ))}
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={4}>
              <Stack spacing={2}>
                {[1, 2, 3].map((i) => (
                  <Card key={i}>
                    <CardContent sx={{ p: 2 }}>
                      <Box sx={{ height: 60, bgcolor: "action.hover", borderRadius: 1 }} />
                    </CardContent>
                  </Card>
                ))}
              </Stack>
            </Grid>
          </Grid>
        )}
      </Stack>
    </Container>
  );
}
