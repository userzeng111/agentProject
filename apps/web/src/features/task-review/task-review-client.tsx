"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  TextField,
  Typography,
} from "@mui/material";
import {
  NavigateNext as NavigateNextIcon,
  CheckCircle as CheckCircleIcon,
  Edit as EditIcon,
  PlayArrow as PlayIcon,
  MenuBook as MenuBookIcon,
} from "@mui/icons-material";
import { fetchTextRef, getReview, resumeTask } from "@/lib/api";
import { ReviewResponse } from "@/lib/types";

const WORKFLOW_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "运行", icon: <PlayIcon fontSize="small" /> },
  { label: "审核", icon: <CheckCircleIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

export default function TaskReviewClient({ taskId }: { taskId: string }) {
  const router = useRouter();
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [outlineMarkdown, setOutlineMarkdown] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadReview() {
      try {
        const nextReview = await getReview(taskId);
        setReview(nextReview);
        setOutlineMarkdown(nextReview.outline_markdown ?? "");
        setError("");

        if (!nextReview.outline_markdown && nextReview.outline_md_ref) {
          const markdown = await fetchTextRef(nextReview.outline_md_ref);
          setOutlineMarkdown(markdown);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "读取审核信息失败");
      }
    }

    void loadReview();
  }, [taskId]);

  async function handleDecision(approved: boolean) {
    try {
      setSubmitting(true);
      const nextTask = await resumeTask(taskId, approved, comment);
      setError("");
      router.push(nextTask.status === "completed" ? `/result/${taskId}` : `/tasks/${taskId}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "提交审核失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (!review) {
    return (
      <Box sx={{ py: 6 }}>
        <Typography>正在载入审核信息...</Typography>
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
        <Typography variant="body2">大纲审核</Typography>
      </Breadcrumbs>

      {/* 步骤指示器 */}
      <Card className="glass-card">
        <CardContent sx={{ py: 2 }}>
          <Stack direction="row" justifyContent="center" spacing={0} sx={{ width: "100%" }}>
            {WORKFLOW_STEPS.map((step, index) => {
              const isDone = index < 2;
              const isActive = index === 2;
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

      {/* 标题 */}
      <Stack spacing={1}>
        <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
          大纲审核
        </Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip label={review.meta.title || taskId} size="small" />
          <Chip label={`版本 ${review.review_version}`} size="small" variant="outlined" />
          <Chip label={review.review_type} size="small" variant="outlined" />
        </Stack>
      </Stack>

      {/* 审核摘要 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">审核摘要</Typography>
            <Typography>{review.summary || review.meta.summary || "暂无审核摘要"}</Typography>
            <Typography color="text.secondary">
              当前阶段：{review.meta.current_stage} · 状态：{review.meta.status}
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      {/* 风险提示 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">风险提示</Typography>
            <List dense>
              {review.risk_flags.length ? (
                review.risk_flags.map((flag, index) => (
                  <ListItem key={`${flag}-${index}`} disableGutters>
                    <Chip label={flag} size="small" color="warning" variant="outlined" sx={{ mr: 1 }} />
                  </ListItem>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="当前没有风险提示。" />
                </ListItem>
              )}
            </List>
          </Stack>
        </CardContent>
      </Card>

      {/* 大纲内容 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">大纲内容</Typography>
            {outlineMarkdown ? (
              <Typography component="pre" sx={{ fontFamily: "inherit", fontSize: 15, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                {outlineMarkdown}
              </Typography>
            ) : (
              <Alert severity="info">聚合接口暂未返回大纲正文，也没有可读取的 Markdown 引用。</Alert>
            )}
          </Stack>
        </CardContent>
      </Card>

      {/* 审核操作 */}
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">审核操作</Typography>
            {review.review_history?.length ? (
              <Box>
                <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>历史记录</Typography>
                <List dense>
                  {review.review_history.map((item, index) => (
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
              </Box>
            ) : null}
            <TextField
              label="审核意见"
              multiline
              minRows={3}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="例如：通过；或者要求收束得更克制一些。"
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Button disabled={submitting} variant="contained" onClick={() => void handleDecision(true)}>
                通过并继续
              </Button>
              <Button
                disabled={submitting}
                variant="outlined"
                color="error"
                onClick={() => void handleDecision(false)}
              >
                拒绝并返回任务
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}
