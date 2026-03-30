"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { getTask, runTask } from "@/lib/api";
import { TaskRecord } from "@/lib/types";

const statusMap: Record<string, { label: string; color: "default" | "success" | "warning" | "error" }> = {
  created: { label: "待启动", color: "default" },
  waiting_outline_review: { label: "待审核", color: "warning" },
  completed: { label: "已完成", color: "success" },
  cancelled: { label: "已取消", color: "error" },
  failed: { label: "失败", color: "error" },
};

export default function TaskRunClient({ taskId }: { taskId: string }) {
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const refreshTask = useCallback(async () => {
    try {
      const nextTask = await getTask(taskId);
      setTask(nextTask);
      setError("");
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "读取任务失败");
    }
  }, [taskId]);

  useEffect(() => {
    void refreshTask();
  }, [refreshTask]);

  async function handleRun() {
    try {
      setRunning(true);
      const nextTask = await runTask(taskId);
      setTask(nextTask);
      setError("");
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "运行失败");
    } finally {
      setRunning(false);
    }
  }

  if (!task) {
    return (
      <Container maxWidth="md" sx={{ py: 6 }}>
        <Typography>正在读取任务...</Typography>
      </Container>
    );
  }

  const status = statusMap[task.status] ?? statusMap.created;

  return (
    <Container maxWidth="lg" sx={{ py: 6 }}>
      <Stack spacing={3}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between">
          <Stack spacing={1}>
            <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              任务运行台
            </Typography>
            <Typography color="text.secondary">
              当前阶段：{task.current_stage}，进度 {task.progress}%
            </Typography>
          </Stack>
          <Chip color={status.color} label={status.label} sx={{ alignSelf: "flex-start" }} />
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">输入摘要</Typography>
              <Typography>{task.input.prompt}</Typography>
              <Typography color="text.secondary">
                模式：{task.mode} | 题材：{task.input.genre || "未指定"} | 风格：{task.input.style || "未指定"}
              </Typography>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                {task.status === "created" ? (
                  <Button variant="contained" disabled={running} onClick={handleRun}>
                    {running ? "正在生成大纲..." : "开始生成大纲"}
                  </Button>
                ) : null}
                {task.status === "waiting_outline_review" ? (
                  <Button component={Link} href={`/review/${task.id}`} variant="contained">
                    进入大纲审核
                  </Button>
                ) : null}
                {task.status === "completed" ? (
                  <Button component={Link} href={`/result/${task.id}`} variant="contained">
                    查看结果
                  </Button>
                ) : null}
                <Button variant="outlined" onClick={() => void refreshTask()}>
                  刷新状态
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>

        {task.story_plan ? (
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">当前大纲预览</Typography>
                <Typography variant="h6">{task.story_plan.working_title}</Typography>
                <Typography color="text.secondary">{task.story_plan.logline}</Typography>
                <List dense>
                  {task.story_plan.chapter_plan.map((chapter) => (
                    <ListItem key={chapter.number} disableGutters>
                      <ListItemText primary={chapter.title} secondary={chapter.goal} />
                    </ListItem>
                  ))}
                </List>
              </Stack>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardContent>
            <Typography variant="h5" gutterBottom>
              运行轨迹
            </Typography>
            <List dense>
              {task.events.map((event, index) => (
                <ListItem key={`${event.at}-${index}`} disableGutters>
                  <ListItemText primary={event.message} secondary={`${event.stage} · ${new Date(event.at).toLocaleString()}`} />
                </ListItem>
              ))}
            </List>
          </CardContent>
        </Card>
      </Stack>
    </Container>
  );
}
