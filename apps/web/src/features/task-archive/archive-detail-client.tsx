"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Divider,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { NavigateNext as NavigateNextIcon } from "@mui/icons-material";
import { fetchTextRef, getArchiveDetail } from "@/lib/api";
import { ArchiveDetailResponse } from "@/lib/types";

export default function ArchiveDetailClient({ taskId }: { taskId: string }) {
  const [detail, setDetail] = useState<ArchiveDetailResponse | null>(null);
  const [resultMarkdown, setResultMarkdown] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const response = await getArchiveDetail(taskId);
        setDetail(response);
        setResultMarkdown(response.result_markdown ?? "");
        setError("");
        if (!response.result_markdown && response.result_md_ref) {
          setResultMarkdown(await fetchTextRef(response.result_md_ref));
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "读取归档详情失败");
      }
    }

    void load();
  }, [taskId]);

  const traceEvents = useMemo(
    () => (detail?.recent_events ?? []).filter((event) => event.event_type === "trace.summary"),
    [detail],
  );

  if (!detail) {
    return (
      <Box sx={{ py: 6 }}>
        <Typography>正在读取归档详情...</Typography>
      </Box>
    );
  }

  return (
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
            {detail.meta.title} · 模式：{detail.meta.mode} · 模型：{detail.meta.model_id || "默认模型"}
          </Typography>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <Button component={Link} href="/archive" variant="outlined" size="small">
            返回列表
          </Button>
          <Button component={Link} href={`/result/${taskId}`} variant="text" size="small">
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
              题材：{detail.request_preview?.genre || "未指定"} · 风格：{detail.request_preview?.style || "未指定"}
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      {/* 正文内容 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">正文内容</Typography>
            {resultMarkdown ? (
              <Typography component="pre" sx={{ fontFamily: "inherit", fontSize: 16, lineHeight: 1.85, whiteSpace: "pre-wrap" }}>
                {resultMarkdown}
              </Typography>
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
                    <ListItemText
                      primary={`第 ${chapter.number} 章 · ${chapter.title}`}
                      secondary={[chapter.summary, chapter.md_ref ?? ""].filter(Boolean).join(" · ")}
                    />
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
  );
}
