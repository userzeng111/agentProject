"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Container,
  Divider,
  List,
  ListItem,
  ListItemText,
  Snackbar,
  Stack,
  Typography,
} from "@mui/material";
import { NavigateNext as NavigateNextIcon } from "@mui/icons-material";
import { fetchTextRef, getApiBase, getArchiveDetail } from "@/lib/api";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { resultHref } from "@/lib/task-routes";
import { ArchiveDetailResponse } from "@/lib/types";
import MarkdownContent from "@/components/markdown-content";

export default function ArchiveDetailClient({ taskId }: { taskId?: string }) {
  const searchParams = useSearchParams();
  const resolvedTaskId = taskId || searchParams.get("id") || "";
  const [detail, setDetail] = useState<ArchiveDetailResponse | null>(null);
  const [resultMarkdown, setResultMarkdown] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMsg, setSnackbarMsg] = useState("");

  /** 显示 snackbar 提示 */
  const showSnackbar = useCallback((msg: string) => {
    setSnackbarMsg(msg);
    setSnackbarOpen(true);
  }, []);

  /** 复制全文到剪贴板 */
  const handleCopy = useCallback(async () => {
    if (!resultMarkdown) return;
    try {
      await navigator.clipboard.writeText(resultMarkdown);
      showSnackbar("已复制到剪贴板");
    } catch {
      showSnackbar("复制失败，请手动选择复制");
    }
  }, [resultMarkdown, showSnackbar]);

  /** 导出为 Markdown 文件下载 */
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

  const traceEvents = useMemo(
    () => (detail?.recent_events ?? []).filter((event) => event.event_type === "trace.summary"),
    [detail],
  );

  if (loading && !detail) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Box sx={{ py: 6 }}>
          <Typography>正在读取归档详情...</Typography>
        </Box>
      </Container>
    );
  }

  if (!detail) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2} sx={{ py: 6 }}>
          <Alert severity="error">{error || "读取归档详情失败"}</Alert>
          <Box>
            <Button variant="outlined" onClick={() => void load()}>
              重新加载
            </Button>
          </Box>
        </Stack>
      </Container>
    );
  }

  const resolveRefHref = (ref?: string | null) => {
    if (!ref) {
      return undefined;
    }
    return ref.startsWith("http") ? ref : `${getApiBase()}${ref}`;
  };

  return (
    <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
    <Stack spacing={3} className="page-fade-in">
      {/* 面包屑 */}
      <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
        <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
          <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
            首页
          </Typography>
        </Link>
        <Link href="/archive" style={{ color: "inherit", textDecoration: "none" }}>
          <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
            归档
          </Typography>
        </Link>
        <Typography variant="body2">{detail.meta.title}</Typography>
      </Breadcrumbs>

      {/* 标题 + 操作 */}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }}>
        <Stack spacing={1}>
          <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            归档详情
          </Typography>
          <Typography color="text.secondary">
            {detail.meta.title} · 类型：
            {formatTaskTypeLabel({
              creativeMode: detail.meta.creative_mode,
              novelSize: detail.meta.novel_size,
              mode: detail.meta.mode,
            })}
            {" · "}任务默认模型：{detail.meta.default_model_id || detail.meta.model_id || "默认模型"}
            {detail.meta.last_action_model_id ? ` · 最近一次动作模型：${detail.meta.last_action_model_id}` : ""}
          </Typography>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <Button component={Link} href="/archive" variant="outlined" size="small">
            返回列表
          </Button>
          <Button component={Link} href={resultHref(resolvedTaskId)} variant="text" size="small">
            结果页视图
          </Button>
        </Stack>
      </Stack>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {/* 请求摘要 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">请求摘要</Typography>
            <Typography>{detail.request_preview?.prompt || "暂无请求摘要"}</Typography>
            <Typography color="text.secondary">
              题材：{detail.request_preview?.genre || "未指定"} · 风格：{detail.request_preview?.style || "未指定"} · 单章字数下限：
              {detail.request_preview?.chapter_word_min ?? detail.meta.chapter_word_min ?? "未指定"}
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      {/* 正文内容 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="h5">正文内容</Typography>
              {resultMarkdown ? (
                <Stack direction="row" spacing={1}>
                  <Button size="small" variant="outlined" onClick={() => void handleCopy()}>
                    复制全文
                  </Button>
                  <Button size="small" variant="outlined" onClick={handleExportMd}>
                    导出 MD
                  </Button>
                </Stack>
              ) : null}
            </Stack>
            {resultMarkdown ? (
              <MarkdownContent variant="article">
                {resultMarkdown}
              </MarkdownContent>
            ) : (
              <Alert severity="warning">当前没有可读取的归档正文。</Alert>
            )}
          </Stack>
        </CardContent>
      </Card>

      {/* 过程摘要流 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">过程摘要流</Typography>
            <List dense>
              {traceEvents.length ? (
                traceEvents.map((event) => (
                  <ListItem key={event.event_id} disableGutters>
                    <ListItemText
                      primary={String(event.payload?.title || event.message)}
                      secondary={[
                        event.payload?.detail,
                        `${event.stage} · ${new Date(event.created_at).toLocaleString()}`,
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

      {/* 章节索引 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">章节索引</Typography>
            <List dense>
              {detail.chapter_index.length ? (
                detail.chapter_index.map((chapter) => (
                  <ListItem key={`${chapter.number}-${chapter.title}`} disableGutters>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      spacing={1}
                      justifyContent="space-between"
                      alignItems={{ xs: "flex-start", sm: "center" }}
                      sx={{ width: "100%" }}
                    >
                      <ListItemText
                        primary={`第 ${chapter.number} 章 · ${chapter.title}`}
                        secondary={chapter.summary || "暂无摘要"}
                      />
                      {chapter.md_ref ? (
                        <Button
                          component="a"
                          href={resolveRefHref(chapter.md_ref)}
                          target="_blank"
                          rel="noreferrer"
                          size="small"
                        >
                          查看章节文件
                        </Button>
                      ) : null}
                    </Stack>
                  </ListItem>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="暂无章节索引。" />
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
            <Typography variant="h5">事件尾流</Typography>
            <List dense>
              {detail.recent_events.length ? (
                detail.recent_events.map((event) => (
                  <div key={event.event_id}>
                    <ListItem disableGutters>
                      <ListItemText
                        primary={event.message}
                        secondary={`${event.stage} · ${event.event_type} · ${new Date(event.created_at).toLocaleString()}`}
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
    {/* 操作反馈提示 */}
    <Snackbar
      open={snackbarOpen}
      autoHideDuration={2500}
      onClose={() => setSnackbarOpen(false)}
      message={snackbarMsg}
      anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
    />
    </Container>
  );
}
