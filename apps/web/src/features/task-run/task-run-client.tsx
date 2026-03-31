"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Avatar,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Divider,
  List,
  ListItem,
  ListItemText,
  Stack,
  LinearProgress,
  Typography,
} from "@mui/material";
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
      <Container maxWidth="md" sx={{ py: 6 }}>
        <Typography>正在读取工作台...</Typography>
      </Container>
    );
  }

  const status = statusMap[workspace.meta.status] ?? statusMap.created;
  const systemStages = buildSystemStages(workspace.recent_events);
  const chapterProgress = buildChapterProgress(workspace.recent_events);
  const summaryStream = buildSummaryStream(workspace.recent_events, workspace.active_trace_summary);

  return (
    <Container maxWidth="lg" sx={{ py: 6 }}>
      <Stack spacing={3}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between">
          <Stack spacing={1}>
            <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              任务工作台
            </Typography>
            <Typography color="text.secondary">
              {workspace.meta.title || taskId} · 当前阶段：{workspace.meta.current_stage} · 进度 {workspace.meta.progress}%
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {streamState}
            </Typography>
          </Stack>
          <Chip color={status.color} label={status.label} sx={{ alignSelf: "flex-start" }} />
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">请求摘要</Typography>
              <Typography>{workspace.request_preview?.prompt || workspace.meta.summary || "暂无请求摘要"}</Typography>
              <Typography color="text.secondary">
                模式：{workspace.meta.mode} | 题材：{workspace.request_preview?.genre || "未指定"} | 风格：
                {workspace.request_preview?.style || "未指定"}
              </Typography>
              {typeof workspace.request_preview?.target_words === "number" ? (
                <Typography color="text.secondary">
                  目标字数：{workspace.request_preview.target_words} · 读者：{workspace.request_preview.audience || "未指定"} ·
                  模型：{workspace.request_preview.model_id || workspace.meta.model_id || "默认模型"}
                </Typography>
              ) : null}
              {workspace.active_trace_summary ? (
                <Typography color="text.secondary">执行摘要：{workspace.active_trace_summary}</Typography>
              ) : null}
              {workspace.available_tabs?.length ? (
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {workspace.available_tabs.map((tab) => (
                    <Chip key={tab} label={tab} size="small" variant="outlined" />
                  ))}
                </Stack>
              ) : null}
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                {["created", "sources_ingested"].includes(workspace.meta.status) ? (
                  <Button variant="contained" disabled={running} onClick={handleRun}>
                    {running ? "正在启动任务..." : "开始执行"}
                  </Button>
                ) : null}
                {workspace.meta.status === "waiting_outline_review" ? (
                  <Button component={Link} href={`/review/${workspace.meta.task_id}`} variant="contained">
                    进入审核页
                  </Button>
                ) : null}
                {workspace.meta.status === "completed" ? (
                  <Button component={Link} href={`/result/${workspace.meta.task_id}`} variant="contained">
                    查看结果页
                  </Button>
                ) : null}
                <Button variant="outlined" onClick={() => void refreshWorkspace()}>
                  刷新状态
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">任务元信息</Typography>
              <Typography color="text.secondary">
                Task ID：{workspace.meta.task_id} · 最近更新时间：
                {workspace.meta.updated_at ? new Date(workspace.meta.updated_at).toLocaleString() : "未提供"}
              </Typography>
              {workspace.meta.current_unit ? (
                <Typography color="text.secondary">当前单元：{workspace.meta.current_unit}</Typography>
              ) : null}
              <LinearProgress
                variant="determinate"
                value={workspace.meta.progress}
                sx={{ height: 10, borderRadius: 999 }}
              />
              <Typography color="text.secondary">{workspace.meta.summary || "暂无摘要"}</Typography>
            </Stack>
          </CardContent>
        </Card>

        <Stack direction={{ xs: "column", xl: "row" }} spacing={3} alignItems="stretch">
          <Card sx={{ flex: 1 }}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">系统阶段</Typography>
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
              </Stack>
            </CardContent>
          </Card>

          <Card sx={{ flex: 1 }}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">章节进度</Typography>
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
              </Stack>
            </CardContent>
          </Card>

          <Card sx={{ flex: 1 }}>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">过程摘要流</Typography>
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
                      <ListItemText primary="暂无过程摘要流" />
                    </ListItem>
                  )}
                </List>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </Stack>
    </Container>
  );
}
