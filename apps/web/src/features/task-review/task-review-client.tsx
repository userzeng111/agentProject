"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  TextField,
  Typography,
} from "@mui/material";
import { fetchTextRef, getReview, resumeTask } from "@/lib/api";
import { ReviewResponse } from "@/lib/types";

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
      <Container maxWidth="md" sx={{ py: 6 }}>
        <Typography>正在载入审核信息...</Typography>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: 6 }}>
      <Stack spacing={3}>
        <Stack spacing={1}>
          <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            大纲审核
          </Typography>
          <Typography color="text.secondary">
            {review.meta.title || taskId} · 版本 {review.review_version} · 类型 {review.review_type}
          </Typography>
        </Stack>
        {error ? <Alert severity="error">{error}</Alert> : null}
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">审核摘要</Typography>
              <Typography>{review.summary || review.meta.summary || "暂无审核摘要"}</Typography>
              <Typography color="text.secondary">
                当前阶段：{review.meta.current_stage} · 当前状态：{review.meta.status}
              </Typography>
            </Stack>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">风险提示</Typography>
              <List dense>
                {review.risk_flags.length ? (
                  review.risk_flags.map((flag, index) => (
                    <ListItem key={`${flag}-${index}`} disableGutters>
                      <ListItemText primary={flag} />
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

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">历史记录</Typography>
              <List dense>
                {review.review_history?.length ? (
                  review.review_history.map((item, index) => (
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
                    <ListItemText primary="暂无审核历史。" />
                  </ListItem>
                )}
              </List>
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
                  color="secondary"
                  onClick={() => void handleDecision(false)}
                >
                  拒绝并返回任务
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      </Stack>
    </Container>
  );
}
