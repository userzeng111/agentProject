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
import { getTask, resumeTask } from "@/lib/api";
import { TaskRecord } from "@/lib/types";

export default function TaskReviewClient({ taskId }: { taskId: string }) {
  const router = useRouter();
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void getTask(taskId).then(setTask).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "读取任务失败");
    });
  }, [taskId]);

  async function handleDecision(approved: boolean) {
    try {
      setSubmitting(true);
      const nextTask = await resumeTask(taskId, approved, comment);
      setTask(nextTask);
      setError("");
      router.push(approved ? `/result/${taskId}` : `/tasks/${taskId}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "提交审核失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (!task) {
    return (
      <Container maxWidth="md" sx={{ py: 6 }}>
        <Typography>正在载入审核信息...</Typography>
      </Container>
    );
  }

  if (!task.pending_review || !task.story_plan) {
    return (
      <Container maxWidth="md" sx={{ py: 6 }}>
        <Alert severity="warning">当前任务没有待审核的大纲。</Alert>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: 6 }}>
      <Stack spacing={3}>
        <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
          大纲审核
        </Typography>
        {error ? <Alert severity="error">{error}</Alert> : null}
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">{task.story_plan.working_title}</Typography>
              <Typography>{task.story_plan.logline}</Typography>
              <Typography variant="subtitle1">世界观线索</Typography>
              <List dense>
                {task.story_plan.world_notes.map((item, index) => (
                  <ListItem key={`${item}-${index}`} disableGutters>
                    <ListItemText primary={item} />
                  </ListItem>
                ))}
              </List>
              <Typography variant="subtitle1">章节计划</Typography>
              <List dense>
                {task.story_plan.chapter_plan.map((chapter) => (
                  <ListItem key={chapter.number} disableGutters>
                    <ListItemText primary={chapter.title} secondary={chapter.goal} />
                  </ListItem>
                ))}
              </List>
              <Typography variant="subtitle1">风险提示</Typography>
              <List dense>
                {task.pending_review.risk_flags.map((flag, index) => (
                  <ListItem key={`${flag}-${index}`} disableGutters>
                    <ListItemText primary={flag} />
                  </ListItem>
                ))}
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
                  通过并继续生成正文
                </Button>
                <Button disabled={submitting} variant="outlined" color="secondary" onClick={() => void handleDecision(false)}>
                  取消本次任务
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      </Stack>
    </Container>
  );
}
