"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Divider,
  List,
  ListItem,
  ListItemText,
  Paper,
  Snackbar,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { fetchTextRef, getArchiveDetail } from "@/lib/api";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { projectViewHref } from "@/lib/task-routes";
import { ArchiveDetailResponse, ResultChapterItem, StoryPlan, WorkspaceEvent } from "@/lib/types";
import { NovelReader } from "@/components/novel-reader";
import { ProjectShell } from "@/components/project-shell";

type TabValue = "overview" | "outline" | "read" | "meta";

const TAB_LABELS: Record<TabValue, string> = {
  overview: "概览",
  outline: "大纲",
  read: "章节阅读",
  meta: "原始信息",
};

const TAB_ORDER: TabValue[] = ["overview", "outline", "read", "meta"];

function getValidTab(raw: string | null): TabValue {
  if (raw && TAB_ORDER.includes(raw as TabValue)) return raw as TabValue;
  return "overview";
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN");
  } catch {
    return iso;
  }
}

function countTextChars(text?: string | null): number {
  if (!text) return 0;
  // 统计中文字符 + 英文单词近似字数
  const cnChars = (text.match(/[一-龥]/g) || []).length;
  const enWords = (text.match(/[a-zA-Z]+/g) || []).length;
  return cnChars + enWords;
}

// ─────────────────────────────────────────────
// 概览 Tab
// ─────────────────────────────────────────────
function OverviewTab({ detail }: { detail: ArchiveDetailResponse }) {
  const chapters = detail.chapter_index;
  const totalChapters = chapters.length;
  const totalChars = useMemo(
    () => chapters.reduce((sum: number, ch: ResultChapterItem) => sum + countTextChars(ch.content), 0),
    [chapters],
  );
  const genre = detail.request_preview?.genre || "未指定";
  const style = detail.request_preview?.style || "未指定";
  const wordMin = detail.request_preview?.chapter_word_min ?? detail.meta.chapter_word_min ?? "未指定";

  return (
    <Stack spacing={3}>
      {/* 小说标题卡 */}
      <Paper elevation={0} sx={{ p: 4, textAlign: "center", bgcolor: "transparent" }}>
        <Typography
          variant="h2"
          sx={{
            fontFamily: "var(--font-serif-sc)",
            fontSize: { xs: "1.75rem", md: "2.25rem" },
            fontWeight: 700,
            mb: 1,
          }}
        >
          {detail.meta.title}
        </Typography>
        <Typography color="text.secondary">
          {formatTaskTypeLabel({
            creativeMode: detail.meta.creative_mode,
            novelSize: detail.meta.novel_size,
            mode: detail.meta.mode,
          })}
        </Typography>
      </Paper>

      {/* 统计信息 */}
      <Card>
        <CardContent>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={3}
            justifyContent="center"
            alignItems="center"
            divider={<Divider orientation="vertical" flexItem />}
          >
            <Box textAlign="center">
              <Typography variant="h4" color="primary.main" sx={{ fontWeight: 700 }}>
                {totalChars.toLocaleString("zh-CN")}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                总字数
              </Typography>
            </Box>
            <Box textAlign="center">
              <Typography variant="h4" color="primary.main" sx={{ fontWeight: 700 }}>
                {totalChapters}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                总章节
              </Typography>
            </Box>
            <Box textAlign="center">
              <Typography variant="h4" color="primary.main" sx={{ fontWeight: 700 }}>
                {typeof wordMin === "number" ? `${wordMin}+` : wordMin}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                单章字数
              </Typography>
            </Box>
          </Stack>
          <Stack direction="row" spacing={1} justifyContent="center" sx={{ mt: 2 }}>
            <Chip label={`题材：${genre}`} size="small" variant="outlined" />
            <Chip label={`风格：${style}`} size="small" variant="outlined" />
          </Stack>
        </CardContent>
      </Card>

      {/* 小说摘要 */}
      {detail.result_summary ? (
        <Card>
          <CardContent>
            <Typography variant="h6" sx={{ mb: 2, fontFamily: "var(--font-serif-sc)" }}>
              简介
            </Typography>
            <Typography sx={{ lineHeight: 1.8, textIndent: "2em" }}>
              {detail.result_summary}
            </Typography>
          </CardContent>
        </Card>
      ) : null}
    </Stack>
  );
}

// ─────────────────────────────────────────────
// 大纲 Tab
// ─────────────────────────────────────────────
function OutlineTab({ storyPlan }: { storyPlan?: StoryPlan | null }) {
  if (!storyPlan) {
    return (
      <Alert severity="info">当前归档任务没有保存故事大纲信息。</Alert>
    );
  }

  return (
    <Stack spacing={3}>
      {/* 故事梗概 */}
      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2, fontFamily: "var(--font-serif-sc)" }}>
            故事梗概
          </Typography>
          <Typography sx={{ lineHeight: 1.8, textIndent: "2em", fontSize: "1.05rem" }}>
            {storyPlan.logline}
          </Typography>
        </CardContent>
      </Card>

      {/* 世界观 */}
      {storyPlan.world_notes.length > 0 ? (
        <Card>
          <CardContent>
            <Typography variant="h6" sx={{ mb: 2, fontFamily: "var(--font-serif-sc)" }}>
              世界观
            </Typography>
            <Stack spacing={1}>
              {storyPlan.world_notes.map((note: string, idx: number) => (
                <Typography key={idx} sx={{ lineHeight: 1.8, textIndent: "2em" }}>
                  {note}
                </Typography>
              ))}
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {/* 人物设定 */}
      {storyPlan.character_notes.length > 0 ? (
        <Card>
          <CardContent>
            <Typography variant="h6" sx={{ mb: 2, fontFamily: "var(--font-serif-sc)" }}>
              人物设定
            </Typography>
            <Stack spacing={1}>
              {storyPlan.character_notes.map((note: string, idx: number) => (
                <Typography key={idx} sx={{ lineHeight: 1.8, textIndent: "2em" }}>
                  {note}
                </Typography>
              ))}
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {/* 章节计划 */}
      <Card>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2, fontFamily: "var(--font-serif-sc)" }}>
            章节计划
          </Typography>
          <List dense>
            {storyPlan.chapter_plan.map((ch: { number: number; title: string; goal: string }) => (
              <ListItem key={ch.number} disableGutters sx={{ py: 0.5 }}>
                <ListItemText
                  primary={`第 ${ch.number} 章 · ${ch.title}`}
                  secondary={ch.goal}
                  primaryTypographyProps={{ fontWeight: 500 }}
                />
              </ListItem>
            ))}
          </List>
        </CardContent>
      </Card>
    </Stack>
  );
}

// ─────────────────────────────────────────────
// 原始信息 Tab
// ─────────────────────────────────────────────
function MetaTab({
  detail,
  resultMarkdown,
  onCopy,
  onExport,
}: {
  detail: ArchiveDetailResponse;
  resultMarkdown: string;
  onCopy: () => void;
  onExport: () => void;
}) {
  const traceEvents = useMemo(
    () => (detail.recent_events ?? []).filter((event: WorkspaceEvent) => event.event_type === "trace.summary"),
    [detail.recent_events],
  );

  return (
    <Stack spacing={3}>
      {/* 请求摘要 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              请求摘要
            </Typography>
            <Typography>{detail.request_preview?.prompt || "暂无请求摘要"}</Typography>
            <Typography color="text.secondary">
              题材：{detail.request_preview?.genre || "未指定"} · 风格：
              {detail.request_preview?.style || "未指定"} · 单章字数下限：
              {detail.request_preview?.chapter_word_min ?? detail.meta.chapter_word_min ?? "未指定"}
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      {/* 操作按钮 */}
      <Paper
        elevation={0}
        sx={{
          p: 2,
          display: "flex",
          justifyContent: "center",
          gap: 2,
          bgcolor: "background.paper",
          borderRadius: 2,
          border: "1px solid",
          borderColor: "divider",
        }}
      >
        <Button variant="outlined" size="small" onClick={onCopy} disabled={!resultMarkdown}>
          复制全文
        </Button>
        <Button variant="outlined" size="small" onClick={onExport} disabled={!resultMarkdown}>
          导出 MD
        </Button>
      </Paper>

      {/* 过程摘要流 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              过程摘要流
            </Typography>
            <List dense>
              {traceEvents.length ? (
                traceEvents.map((event: WorkspaceEvent) => (
                  <ListItem key={event.event_id} disableGutters>
                    <ListItemText
                      primary={String(event.payload?.title || event.message)}
                      secondary={[
                        event.payload?.detail,
                        `${event.stage} · ${formatDateTime(event.created_at)}`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    />
                  </ListItem>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="当前归档任务没有过程摘要流。" />
                </ListItem>
              )}
            </List>
          </Stack>
        </CardContent>
      </Card>

      {/* 事件尾流 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h6" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              事件尾流
            </Typography>
            <List dense>
              {detail.recent_events.length ? (
                detail.recent_events.map((event: WorkspaceEvent) => (
                  <div key={event.event_id}>
                    <ListItem disableGutters>
                      <ListItemText
                        primary={event.message}
                        secondary={`${event.stage} · ${event.event_type} · ${formatDateTime(event.created_at)}`}
                      />
                    </ListItem>
                    <Divider component="li" />
                  </div>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="暂无事件尾流。" />
                </ListItem>
              )}
            </List>
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}

// ─────────────────────────────────────────────
// 主组件
// ─────────────────────────────────────────────
export default function ArchiveDetailClient({ taskId }: { taskId?: string }) {
  const searchParams = useSearchParams();
  const resolvedTaskId = taskId || searchParams.get("id") || "";
  const [detail, setDetail] = useState<ArchiveDetailResponse | null>(null);
  const [resultMarkdown, setResultMarkdown] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMsg, setSnackbarMsg] = useState("");
  const [activeTab, setActiveTab] = useState<TabValue>(() =>
    getValidTab(searchParams.get("tab")),
  );

  const showSnackbar = useCallback((msg: string) => {
    setSnackbarMsg(msg);
    setSnackbarOpen(true);
  }, []);

  const handleCopy = useCallback(async () => {
    if (!resultMarkdown) return;
    try {
      await navigator.clipboard.writeText(resultMarkdown);
      showSnackbar("已复制到剪贴板");
    } catch {
      showSnackbar("复制失败，请手动选择复制");
    }
  }, [resultMarkdown, showSnackbar]);

  const handleExportMd = useCallback(() => {
    if (!resultMarkdown) return;
    const blob = new Blob([resultMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${detail?.meta.title || resolvedTaskId || "archive"}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showSnackbar("已导出 Markdown 文件");
  }, [resultMarkdown, detail?.meta.title, resolvedTaskId, showSnackbar]);

  const load = useCallback(async () => {
    if (!resolvedTaskId) {
      setError("缺少任务 ID");
      setDetail(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const response = await getArchiveDetail(resolvedTaskId);
      setDetail(response);
      setResultMarkdown(response.result_markdown ?? "");
      setError("");
      if (!response.result_markdown && response.result_md_ref) {
        setResultMarkdown(await fetchTextRef(response.result_md_ref));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取归档详情失败");
    } finally {
      setLoading(false);
    }
  }, [resolvedTaskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleTabChange = (_: React.SyntheticEvent, newValue: TabValue) => {
    setActiveTab(newValue);
    // 同步到 URL（不触发路由跳转，仅更新 query param）
    const url = new URL(window.location.href);
    url.searchParams.set("tab", newValue);
    window.history.replaceState({}, "", url.toString());
  };

  if (loading && !detail) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Box sx={{ py: 6 }} role="status" aria-live="polite">
          <Typography>正在读取归档详情...</Typography>
        </Box>
      </Container>
    );
  }

  if (!detail) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2} sx={{ py: 6 }}>
          <Alert severity="error" role="alert">{error || "读取归档详情失败"}</Alert>
          <Box>
            <Button variant="outlined" onClick={() => void load()}>
              重新加载
            </Button>
          </Box>
        </Stack>
      </Container>
    );
  }

  const taskTypeLabel = formatTaskTypeLabel({
    creativeMode: detail.meta.creative_mode,
    novelSize: detail.meta.novel_size,
    mode: detail.meta.mode,
  });

  return (
    <ProjectShell
      breadcrumbs={[
        { label: "首页", href: "/" },
        { label: "归档", href: "/archive" },
        { label: detail.meta.title },
      ]}
      title="归档详情"
      metaItems={[
        { label: detail.meta.title },
        { label: `类型：${taskTypeLabel}`, variant: "outlined" },
        { label: `任务创作模型：${detail.meta.creative_model_id || detail.meta.model_id || "未设置"}`, variant: "outlined" },
        ...(detail.meta.last_action_model_id
          ? [{ label: `最近一次动作模型：${detail.meta.last_action_model_id}`, variant: "outlined" as const }]
          : []),
      ]}
      actions={
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <Button component={Link} href="/archive" variant="outlined" size="small">
            返回列表
          </Button>
          <Button component={Link} href={projectViewHref(resolvedTaskId, "result")} variant="text" size="small">
            结果页视图
          </Button>
        </Stack>
      }
    >

        {error ? <Alert severity="error" role="alert">{error}</Alert> : null}

        {/* Tab 导航 */}
        <Box sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Tabs
            value={activeTab}
            onChange={handleTabChange}
            variant="scrollable"
            scrollButtons="auto"
            allowScrollButtonsMobile
            aria-label="归档详情视图"
          >
            {TAB_ORDER.map((tab) => (
              <Tab key={tab} value={tab} label={TAB_LABELS[tab]} />
            ))}
          </Tabs>
        </Box>

        {/* Tab 内容 */}
        <Box sx={{ minHeight: 400 }}>
          {activeTab === "overview" && <OverviewTab detail={detail} />}
          {activeTab === "outline" && <OutlineTab storyPlan={detail.story_plan} />}
          {activeTab === "read" && <NovelReader chapters={detail.chapter_index} />}
          {activeTab === "meta" && (
            <MetaTab
              detail={detail}
              resultMarkdown={resultMarkdown}
              onCopy={handleCopy}
              onExport={handleExportMd}
            />
          )}
        </Box>

      <Snackbar
        open={snackbarOpen}
        autoHideDuration={2500}
        onClose={() => setSnackbarOpen(false)}
        message={snackbarMsg}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </ProjectShell>
  );
}
