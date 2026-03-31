"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Container,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { fetchTextRef, getResult } from "@/lib/api";
import { ResultResponse } from "@/lib/types";

export default function TaskResultClient({ taskId }: { taskId: string }) {
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [resultMarkdown, setResultMarkdown] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const response = await getResult(taskId);
        setResult(response);
        setResultMarkdown(response.result_markdown ?? "");
        setError("");

        if (!response.result_markdown && response.result_md_ref) {
          const markdown = await fetchTextRef(response.result_md_ref);
          setResultMarkdown(markdown);
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "读取结果失败");
      }
    }

    void load();
  }, [taskId]);

  if (!result) {
    return (
      <Container maxWidth="md" sx={{ py: 6 }}>
        <Typography>正在读取结果...</Typography>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: 6 }}>
      <Stack spacing={3}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between">
          <Stack spacing={1}>
            <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              生成结果
            </Typography>
            <Typography color="text.secondary">
              {result.meta.title || taskId} · 当前状态：{result.meta.status} · 阶段：{result.meta.current_stage}
            </Typography>
          </Stack>
          <Button component={Link} href={`/tasks/${taskId}`} variant="outlined">
            返回工作台
          </Button>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">结果摘要</Typography>
              <Typography>{result.result_summary || result.meta.summary || "暂无结果摘要"}</Typography>
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">正文内容</Typography>
              {resultMarkdown ? (
                <Typography component="pre" sx={{ fontFamily: "inherit", fontSize: 16, lineHeight: 1.85, whiteSpace: "pre-wrap" }}>
                  {resultMarkdown}
                </Typography>
              ) : (
                <Alert severity="warning">当前任务还没有可展示的正文结果。</Alert>
              )}
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">章节索引</Typography>
              <List dense>
                {result.chapter_index.length ? (
                  result.chapter_index.map((chapter) => (
                    <ListItem key={`${chapter.number}-${chapter.title}`} disableGutters>
                      <ListItemText
                        primary={`第 ${chapter.number} 章 · ${chapter.title}`}
                        secondary={[
                          chapter.summary,
                          chapter.content ? "已内联正文" : "",
                          chapter.md_ref ?? "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
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

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">工件索引</Typography>
              <List dense>
                {result.artifact_index.length ? (
                  result.artifact_index.map((artifact) => (
                    <ListItem key={artifact.id} disableGutters>
                      <ListItemText
                        primary={artifact.name}
                        secondary={[artifact.type, artifact.md_ref ?? "", artifact.json_ref ?? ""].filter(Boolean).join(" · ")}
                      />
                    </ListItem>
                  ))
                ) : (
                  <ListItem disableGutters>
                    <ListItemText primary="暂无工件索引。" />
                  </ListItem>
                )}
              </List>
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">历史记录</Typography>
              <List dense>
                {result.history_index?.length ? (
                  result.history_index.map((item, index) => (
                    <ListItem key={`${item.version}-${item.created_at ?? index}`} disableGutters>
                      <ListItemText
                        primary={`${item.version} · ${item.action}`}
                        secondary={[
                          item.comment,
                          item.created_at ? new Date(item.created_at).toLocaleString() : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      />
                    </ListItem>
                  ))
                ) : (
                  <ListItem disableGutters>
                    <ListItemText primary="暂无历史记录。" />
                  </ListItem>
                )}
              </List>
            </Stack>
          </CardContent>
        </Card>
      </Stack>
    </Container>
  );
}
