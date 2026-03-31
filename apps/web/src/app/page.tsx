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
  Stack,
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

function TaskSection({
  title,
  items,
  emptyText,
}: {
  title: string;
  items: TaskCardSummary[];
  emptyText: string;
}) {
  return (
    <Card sx={{ borderRadius: 4 }}>
      <CardContent>
        <Stack spacing={2.5}>
          <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            {title}
          </Typography>
          {items.length ? (
            <Stack spacing={2}>
              {items.map((task) => (
                <Card key={task.task_id} variant="outlined" sx={{ borderRadius: 3 }}>
                  <CardContent>
                    <Stack spacing={1.5}>
                      <Stack
                        direction={{ xs: "column", sm: "row" }}
                        spacing={1}
                        justifyContent="space-between"
                        alignItems={{ xs: "flex-start", sm: "center" }}
                      >
                        <Typography variant="h6">{task.title || task.task_id}</Typography>
                        <Chip label={statusLabelMap[task.status] ?? task.status} size="small" />
                      </Stack>
                      <Typography color="text.secondary">{task.summary}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        阶段：{task.current_stage} · 模式：{task.mode} · 更新时间：
                        {new Date(task.updated_at).toLocaleString()}
                      </Typography>
                      <Button
                        component={Link}
                        href={resolveTaskHref(task)}
                        variant="text"
                        sx={{ alignSelf: "flex-start", px: 0 }}
                      >
                        查看详情
                      </Button>
                    </Stack>
                  </CardContent>
                </Card>
              ))}
            </Stack>
          ) : (
            <Typography color="text.secondary">{emptyText}</Typography>
          )}
        </Stack>
      </CardContent>
    </Card>
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

  const visibleRunningCount = dashboard?.running_tasks?.length ?? 0;
  const reportedActiveRuns = dashboard?.system_summary?.active_runs ?? 0;

  return (
    <Stack spacing={4} className="page-fade-in">
      <Stack spacing={2}>
        <Chip label="LangChain + LangGraph + GPT-5.4" sx={{ alignSelf: "flex-start" }} />
        <Typography
          variant="h2"
          sx={{
            fontFamily: "var(--font-serif-sc)",
            maxWidth: 760,
            lineHeight: 1.12,
          }}
        >
          小说工坊
        </Typography>
        <Typography variant="h6" color="text.secondary" sx={{ maxWidth: 760 }}>
          从灵感到成稿，AI 辅助小说创作。输入创意，审核大纲，生成初稿。
        </Typography>
      </Stack>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
        <Button component={Link} href="/create" size="large" variant="contained">
          创建新任务
        </Button>
        <Button component={Link} href="/archive" size="large" variant="outlined">
          查看归档
        </Button>
      </Stack>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {dashboard ? (
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <Card sx={{ flex: 1 }}>
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="overline">活动运行</Typography>
                <Typography variant="h4">{reportedActiveRuns}</Typography>
                <Typography color="text.secondary">
                  接口统计 {reportedActiveRuns} · 列表展示 {visibleRunningCount}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
          <Card sx={{ flex: 1 }}>
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="overline">归档任务</Typography>
                <Typography variant="h4">{dashboard.system_summary?.archived_runs ?? 0}</Typography>
                <Typography color="text.secondary">已归档运行数</Typography>
                <Button component={Link} href="/archive" variant="text" sx={{ alignSelf: "flex-start", px: 0 }}>
                  进入归档列表
                </Button>
              </Stack>
            </CardContent>
          </Card>
          <Card sx={{ flex: 1 }}>
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="overline">默认模型</Typography>
                <Typography variant="h4">{dashboard.model_summary?.default_model ?? "未提供"}</Typography>
                <Typography color="text.secondary">
                  支持模型 {dashboard.model_summary?.supported_models?.length ?? 0} 个
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: 24,
        }}
      >
        {[
          {
            icon: <ArchiveRoundedIcon />,
            title: "归档回查",
            text: "已完成任务自动归档，随时回看结果与章节。",
          },
          {
            icon: <HubRoundedIcon />,
            title: "先规划后写作",
            text: "大纲审核机制，把控故事走向后再生成正文。",
          },
          {
            icon: <LayersRoundedIcon />,
            title: "多种创作模式",
            text: "短篇、长篇、同人创作、风格复刻，灵活选择。",
          },
          {
            icon: <AutoStoriesRoundedIcon />,
            title: "参考文本",
            text: "上传文本作为世界观或风格参考，融入创作。",
          },
        ].map((item) => (
          <Card key={item.title} className="glass-card">
            <CardContent>
              <Stack spacing={2}>
                <Box
                  sx={{
                    width: 48,
                    height: 48,
                    borderRadius: 3,
                    display: "grid",
                    placeItems: "center",
                    backgroundColor: "rgba(39, 100, 81, 0.10)",
                    color: "primary.main",
                  }}
                >
                  {item.icon}
                </Box>
                <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                  {item.title}
                </Typography>
                <Typography color="text.secondary">{item.text}</Typography>
              </Stack>
            </CardContent>
          </Card>
        ))}
      </div>

      <TaskSection
        title="待继续处理"
        items={dashboard?.continue_tasks ?? []}
        emptyText="当前没有需要人工继续处理的任务。"
      />
      <TaskSection
        title="运行中"
        items={dashboard?.running_tasks ?? []}
        emptyText="当前没有运行中的任务。"
      />
      <TaskSection
        title="失败任务"
        items={dashboard?.failed_tasks ?? []}
        emptyText="当前没有失败任务。"
      />
    </Stack>
  );
}
