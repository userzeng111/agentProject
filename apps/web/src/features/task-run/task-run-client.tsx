"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Avatar,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import {
  NavigateNext as NavigateNextIcon,
  CheckCircle as CheckCircleIcon,
  Edit as EditIcon,
  PlayArrow as PlayIcon,
  MenuBook as MenuBookIcon,
} from "@mui/icons-material";
import { getApiBase, getWorkspace, runTask } from "@/lib/api";
import { TaskStatus, WorkspaceEvent, WorkspaceResponse } from "@/lib/types";

const statusMap: Record<TaskStatus, { label: string; color: "default" | "success" | "warning" | "error" }> = {
  created: { label: "待启动", color: "default" },
  sources_ingested: { label: "素材已入库", color: "default" },
  planning: { label: "规划中", color: "warning" },
  waiting_outline_review: { label: "待审核", color: "warning" },
  drafting: { label: "正文生成中", color: "warning" },
  waiting_manual_action: { label: "待人工处理", color: "warning" },
  assembling: { label: "结果整理中", color: "warning" },
  completed: { label: "已完成", color: "success" },
  cancelled: { label: "已取消", color: "error" },
  failed: { label: "失败", color: "error" },
};

const WORKFLOW_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "运行", icon: <PlayIcon fontSize="small" /> },
  { label: "审核", icon: <CheckCircleIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

function getStepIndex(status: TaskStatus): number {
  if (status === "completed") return 4;
  if (status === "waiting_outline_review" || status === "drafting" || status === "assembling") return 2;
  if (status === "planning" || status === "sources_ingested" || status === "waiting_manual_action") return 1;
  return 0;
}

const streamPathCandidates = (taskId: string) => [
  `/api/tasks/${taskId}/events/stream`,
  `/api/tasks/${taskId}/workspace/stream`,
  `/api/tasks/${taskId}/workspace/events`,
  `/api/tasks/${taskId}/sse`,
];

function formatEventRef(event: WorkspaceEvent) {
  const refs = [event.md_ref, event.json_ref].filter(Boolean);
  return refs.length ? `引用：${refs.join(" · ")}` : "";
}

function formatEventTime(value: string) {
  return new Date(value).toLocaleString();
}

function buildSummaryStream(events: WorkspaceEvent[], activeTraceSummary?: string) {
  const traceEvents = events.filter(
    (event) => event.event_type === "trace.summary" || typeof event.payload?.summary === "string",
  );

  if (traceEvents.length) {
    return traceEvents.map((event) => ({
      id: event.event_id,
      title: String(event.payload?.title || event.payload?.summary || event.message || "过程摘要已更新"),
      subtitle: [event.payload?.detail, `${event.stage} · ${formatEventTime(event.created_at)}`]
        .filter(Boolean)
        .join(" · "),
    }));
  }

  const fallback = events
    .filter((event) => !event.event_type.startsWith("chapter."))
    .slice(-8)
    .map((event) => ({
      id: event.event_id,
      title: event.message,
      subtitle: `${event.stage} · ${formatEventTime(event.created_at)}`,
    }));

  if (!fallback.length && activeTraceSummary) {
    return [
      {
        id: "active-trace-summary",
        title: activeTraceSummary,
        subtitle: "当前过程摘要",
      },
    ];
  }

  return fallback;
}

function buildChapterProgress(events: WorkspaceEvent[]) {
  const chapterMap = new Map<
    number,
    {
      number: number;
      title: string;
      status: string;
      progress: number;
      summary?: string;
      updatedAt: string;
    }
  >();

  events
    .filter((event) => event.event_type.startsWith("chapter."))
    .forEach((event) => {
      const chapterNumber = event.payload?.chapter_number;
      if (typeof chapterNumber !== "number") {
        return;
      }
      const current = chapterMap.get(chapterNumber);
      const title = event.payload?.chapter_title || current?.title || event.unit_id || `第 ${chapterNumber} 章`;
      chapterMap.set(chapterNumber, {
        number: chapterNumber,
        title,
        status: event.event_type === "chapter.saved" ? "已完成" : "生成中",
        progress: event.event_type === "chapter.saved" ? 100 : 56,
        summary: event.payload?.chapter_summary || current?.summary,
        updatedAt: event.created_at,
      });
    });

  return Array.from(chapterMap.values()).sort((left, right) => left.number - right.number);
}

function buildSystemStages(events: WorkspaceEvent[]) {
  return events.filter((event) => !event.event_type.startsWith("chapter.")).slice(-10);
}

export default function TaskRunClient({ taskId }: { taskId: string }) {
  const [workspace, setWorkspace] = useState<WorkspaceResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [streamState, setStreamState] = useState("未连接事件流");
  const [activeTab, setActiveTab] = useState(0);
  const eventSourceRef = useRef<EventSource | null>(null);

  const refreshWorkspace = useCallback(async () => {
    try {
      const nextWorkspace = await getWorkspace(taskId);
      setWorkspace(nextWorkspace);
      setError("");
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "读取工作台失败");
    }
  }, [taskId]);

  useEffect(() => {
    void refreshWorkspace();
  }, [refreshWorkspace]);

  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;

    const tryConnect = (index: number) => {
      if (disposed || index >= streamPathCandidates(taskId).length) {
        if (!disposed) {
          setStreamState("事件流未就绪，当前使用手动刷新");
        }
        return;
      }

      const target = `${getApiBase()}${streamPathCandidates(taskId)[index]}`;
      setStreamState(`正在连接 ${streamPathCandidates(taskId)[index]}`);
      source = new EventSource(target);
      eventSourceRef.current = source;

      let opened = false;

      source.onopen = () => {
        opened = true;
        setStreamState("事件流已连接");
      };

      const handleRefresh = () => {
        void refreshWorkspace();
      };
      source.addEventListener("snapshot", handleRefresh);
      source.addEventListener("task.event", handleRefresh);
      source.addEventListener("task.done", handleRefresh);

      source.onerror = () => {
        source?.close();
        if (disposed) {
          return;
        }
        if (!opened) {
          tryConnect(index + 1);
          return;
        }
        setStreamState("事件流已断开，当前使用手动刷新");
      };
    };

    tryConnect(0);

    return () => {
      disposed = true;
      source?.close();
      eventSourceRef.current = null;
    };
  }, [taskId, refreshWorkspace]);

  async function handleRun() {
    try {
      setRunning(true);
      await runTask(taskId);
      await refreshWorkspace();
      setError("");
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "运行失败");
    } finally {
      setRunning(false);
    }
  }

  if (!workspace) {
    return (
      <Box sx={{ py: 6 }}>
        <Typography>正在读取工作台...</Typography>
      </Box>
    );
  }

  const status = statusMap[workspace.meta.status] ?? statusMap.created;
  const systemStages = buildSystemStages(workspace.recent_events);
  const chapterProgress = buildChapterProgress(workspace.recent_events);
  const summaryStream = buildSummaryStream(workspace.recent_events, workspace.active_trace_summary);
  const currentStep = getStepIndex(workspace.meta.status);

  return (
    <Stack spacing={3} className="page-fade-in">
      {/* 面包屑 + 状态 */}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
        <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
          <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
            <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
              首页
            </Typography>
          </Link>
          <Typography variant="body2">{workspace.meta.title || taskId}</Typography>
        </Breadcrumbs>
        <Chip color={status.color} label={status.label} />
      </Stack>

      {/* 步骤指示器 */}
      <Card className="glass-card">
        <CardContent sx={{ py: 2 }}>
          <Stack direction="row" justifyContent="center" spacing={0} sx={{ width: "100%" }}>
            {WORKFLOW_STEPS.map((step, index) => {
              const isDone = index < currentStep;
              const isActive = index === currentStep;
              return (
                <Box
                  key={step.label}
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    flex: index < WORKFLOW_STEPS.length - 1 ? 1 : 0,
                    justifyContent: "center",
                  }}
                >
                  <Stack spacing={0.5} alignItems="center" sx={{ minWidth: 64 }}>
                    <Box
                      sx={{
                        width: 36,
                        height: 36,
                        borderRadius: "50%",
                        display: "grid",
                        placeItems: "center",
                        backgroundColor: isDone ? "success.main" : isActive ? "primary.main" : "rgba(29,42,39,0.08)",
                        color: "#fff",
                        transition: "all 0.3s",
                      }}
                    >
                      {isDone ? <CheckCircleIcon fontSize="small" /> : step.icon}
                    </Box>
                    <Typography
                      variant="caption"
                      sx={{
                        fontWeight: isActive ? 600 : 400,
                        color: isActive ? "primary.main" : isDone ? "success.main" : "text.secondary",
                      }}
                    >
                      {step.label}
                    </Typography>
                  </Stack>
                  {index < WORKFLOW_STEPS.length - 1 && (
                    <Box
                      sx={{
                        flex: 1,
                        height: 2,
                        mx: 1,
                        mt: -2,
                        backgroundColor: isDone ? "success.main" : "rgba(29,42,39,0.08)",
                        transition: "all 0.3s",
                        borderRadius: 1,
                      }}
                    />
                  )}
                </Box>
              );
            })}
          </Stack>
        </CardContent>
      </Card>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {/* 请求摘要卡片 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }} spacing={1}>
              <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                请求摘要
              </Typography>
              <Stack direction="row" spacing={1}>
                {["created", "sources_ingested"].includes(workspace.meta.status) && (
                  <Button variant="contained" disabled={running} onClick={handleRun} size="small">
                    {running ? "启动中..." : "开始执行"}
                  </Button>
                )}
                {workspace.meta.status === "waiting_outline_review" && (
                  <Button component={Link} href={`/review/${workspace.meta.task_id}`} variant="contained" size="small">
                    进入审核
                  </Button>
                )}
                {workspace.meta.status === "completed" && (
                  <Button component={Link} href={`/result/${workspace.meta.task_id}`} variant="contained" size="small">
                    查看结果
                  </Button>
                )}
                <Button variant="outlined" onClick={() => void refreshWorkspace()} size="small">
                  刷新
                </Button>
              </Stack>
            </Stack>
            <Typography>{workspace.request_preview?.prompt || workspace.meta.summary || "暂无请求摘要"}</Typography>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              <Chip label={`模式: ${workspace.meta.mode}`} size="small" variant="outlined" />
              {workspace.request_preview?.genre && <Chip label={`题材: ${workspace.request_preview.genre}`} size="small" variant="outlined" />}
              {workspace.request_preview?.style && <Chip label={`风格: ${workspace.request_preview.style}`} size="small" variant="outlined" />}
              {workspace.available_tabs?.map((tab) => (
                <Chip key={tab} label={tab} size="small" variant="outlined" />
              ))}
            </Stack>
            {workspace.active_trace_summary && (
              <Typography variant="body2" color="text.secondary">
                执行摘要：{workspace.active_trace_summary}
              </Typography>
            )}
          </Stack>
        </CardContent>
      </Card>

      {/* 进度条 */}
      <Box>
        <Stack direction="row" justifyContent="space-between" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {workspace.meta.current_stage || "初始化中"}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {workspace.meta.progress}%
          </Typography>
        </Stack>
        <LinearProgress
          variant="determinate"
          value={workspace.meta.progress}
          sx={{ height: 8, borderRadius: 999 }}
        />
      </Box>

      {/* Tab 区域 */}
      <Card>
        <Box sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Tabs value={activeTab} onChange={(_, v) => setActiveTab(v)}>
            <Tab label={`实时日志 (${systemStages.length})`} />
            <Tab label={`章节进度 (${chapterProgress.length})`} />
            <Tab label="任务详情" />
          </Tabs>
        </Box>
        <CardContent>
          {/* Tab 0: 实时日志 */}
          {activeTab === 0 && (
            <Stack spacing={3}>
              <Box>
                <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                  {streamState}
                </Typography>
                <List dense>
                  {systemStages.length ? (
                    systemStages.map((event) => (
                      <div key={event.event_id}>
                        <ListItem disableGutters alignItems="flex-start">
                          <ListItemText
                            primary={event.message}
                            secondary={
                              [
                                `${event.stage} · ${event.event_type} · ${formatEventTime(event.created_at)}`,
                                formatEventRef(event),
                              ]
                                .filter(Boolean)
                                .join("\n")
                            }
                            secondaryTypographyProps={{ sx: { whiteSpace: "pre-line" } }}
                          />
                        </ListItem>
                        <Divider component="li" />
                      </div>
                    ))
                  ) : (
                    <ListItem disableGutters>
                      <ListItemText primary="暂无系统阶段事件" />
                    </ListItem>
                  )}
                </List>
              </Box>
              <Divider />
              <Box>
                <Typography variant="h6" sx={{ mb: 1.5 }}>过程摘要流</Typography>
                <List dense>
                  {summaryStream.length ? (
                    summaryStream.map((item) => (
                      <div key={item.id}>
                        <ListItem disableGutters alignItems="flex-start">
                          <Avatar
                            sx={{
                              width: 32,
                              height: 32,
                              mr: 1.5,
                              bgcolor: "rgba(39, 100, 81, 0.12)",
                              color: "primary.main",
                              fontSize: 14,
                            }}
                          >
                            摘
                          </Avatar>
                          <ListItemText primary={item.title} secondary={item.subtitle} />
                        </ListItem>
                        <Divider component="li" />
                      </div>
                    ))
                  ) : (
                    <ListItem disableGutters>
                      <ListItemText primary="暂无过程摘要" />
                    </ListItem>
                  )}
                </List>
              </Box>
            </Stack>
          )}

          {/* Tab 1: 章节进度 */}
          {activeTab === 1 && (
            <List dense>
              {chapterProgress.length ? (
                chapterProgress.map((chapter) => (
                  <div key={chapter.number}>
                    <ListItem disableGutters alignItems="flex-start">
                      <ListItemText
                        primary={`第 ${chapter.number} 章 · ${chapter.title}`}
                        secondary={
                          [
                            `${chapter.status} · ${formatEventTime(chapter.updatedAt)}`,
                            chapter.summary || "",
                          ]
                            .filter(Boolean)
                            .join("\n")
                        }
                        secondaryTypographyProps={{ sx: { whiteSpace: "pre-line" } }}
                      />
                    </ListItem>
                    <LinearProgress
                      variant="determinate"
                      value={chapter.progress}
                      sx={{ mb: 1.5, height: 8, borderRadius: 999 }}
                    />
                    <Divider component="li" />
                  </div>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="当前还没有章节级进度事件" />
                </ListItem>
              )}
            </List>
          )}

          {/* Tab 2: 任务详情 */}
          {activeTab === 2 && (
            <Stack spacing={2}>
              <Stack direction="row" spacing={2}>
                <Typography variant="body2" color="text.secondary">
                  Task ID：{workspace.meta.task_id}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  模型：{workspace.request_preview?.model_id || workspace.meta.model_id || "默认模型"}
                </Typography>
              </Stack>
              {typeof workspace.request_preview?.target_words === "number" && (
                <Typography variant="body2" color="text.secondary">
                  目标字数：{workspace.request_preview.target_words} · 读者：{workspace.request_preview.audience || "未指定"}
                </Typography>
              )}
              {workspace.meta.current_unit && (
                <Typography variant="body2" color="text.secondary">
                  当前单元：{workspace.meta.current_unit}
                </Typography>
              )}
              {workspace.meta.updated_at && (
                <Typography variant="body2" color="text.secondary">
                  最近更新：{new Date(workspace.meta.updated_at).toLocaleString()}
                </Typography>
              )}
              <Typography variant="body2" color="text.secondary">
                {workspace.meta.summary || "暂无摘要"}
              </Typography>
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  );
}
