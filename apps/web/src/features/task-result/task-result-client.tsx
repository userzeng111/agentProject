"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Chip,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import {
  NavigateNext as NavigateNextIcon,
  CheckCircle as CheckCircleIcon,
  Edit as EditIcon,
  PlayArrow as PlayIcon,
  MenuBook as MenuBookIcon,
} from "@mui/icons-material";
import { fetchTextRef, getResult } from "@/lib/api";
import { ResultResponse } from "@/lib/types";

const WORKFLOW_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "运行", icon: <PlayIcon fontSize="small" /> },
  { label: "审核", icon: <CheckCircleIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

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
      <Box sx={{ py: 6 }}>
        <Typography>正在读取结果...</Typography>
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
        <Link href={`/tasks/${taskId}`} style={{ color: "inherit", textDecoration: "none" }}>
          <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
            工作台
          </Typography>
        </Link>
        <Typography variant="body2">生成结果</Typography>
      </Breadcrumbs>

      {/* 步骤指示器 */}
      <Card className="glass-card">
        <CardContent sx={{ py: 2 }}>
          <Stack direction="row" justifyContent="center" spacing={0} sx={{ width: "100%" }}>
            {WORKFLOW_STEPS.map((step, index) => {
              const isDone = index < 3;
              const isActive = index === 3;
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

      {/* 标题 + 操作 */}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }}>
        <Stack spacing={1}>
          <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            生成结果
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip label={result.meta.title || taskId} size="small" />
            <Chip label={result.meta.status} size="small" variant="outlined" />
          </Stack>
        </Stack>
        <Button component={Link} href={`/tasks/${taskId}`} variant="outlined" size="small">
          返回工作台
        </Button>
      </Stack>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {/* 结果摘要 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">结果摘要</Typography>
            <Typography>{result.result_summary || result.meta.summary || "暂无结果摘要"}</Typography>
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
              <Alert severity="warning">当前任务还没有可展示的正文结果。</Alert>
            )}
          </Stack>
        </CardContent>
      </Card>

      {/* 章节索引 */}
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

      {/* 工件索引 */}
      {result.artifact_index.length ? (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">工件索引</Typography>
              <List dense>
                {result.artifact_index.map((artifact) => (
                  <ListItem key={artifact.id} disableGutters>
                    <ListItemText
                      primary={artifact.name}
                      secondary={[artifact.type, artifact.md_ref ?? "", artifact.json_ref ?? ""].filter(Boolean).join(" · ")}
                    />
                  </ListItem>
                ))}
              </List>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {/* 历史记录 */}
      {result.history_index?.length ? (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">历史记录</Typography>
              <List dense>
                {result.history_index.map((item, index) => (
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
                ))}
              </List>
            </Stack>
          </CardContent>
        </Card>
      ) : null}
    </Stack>
  );
}
