"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Container,
  Divider,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { getTask, listArtifacts } from "@/lib/api";
import { ArtifactItem, TaskRecord } from "@/lib/types";

export default function TaskResultClient({ taskId }: { taskId: string }) {
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [taskResponse, artifactResponse] = await Promise.all([getTask(taskId), listArtifacts(taskId)]);
        setTask(taskResponse);
        setArtifacts(artifactResponse);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "读取结果失败");
      }
    }
    void load();
  }, [taskId]);

  if (!task) {
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
              当前状态：{task.status}，可回到任务页查看完整轨迹。
            </Typography>
          </Stack>
          <Button component={Link} href={`/tasks/${taskId}`} variant="outlined">
            返回任务页
          </Button>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        {task.draft_result ? (
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h4" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                  {task.draft_result.title}
                </Typography>
                <Typography color="text.secondary">{task.draft_result.summary}</Typography>
                <Divider />
                <Typography component="pre" sx={{ fontFamily: "inherit", fontSize: 16, lineHeight: 1.85 }}>
                  {task.draft_result.body}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        ) : (
          <Alert severity="warning">当前任务还没有正文结果。</Alert>
        )}

        <Card>
          <CardContent>
            <Typography variant="h5" gutterBottom>
              工件列表
            </Typography>
            <List dense>
              {artifacts.map((artifact) => (
                <ListItem key={artifact.id} disableGutters>
                  <ListItemText primary={artifact.name} secondary={artifact.type} />
                </ListItem>
              ))}
            </List>
          </CardContent>
        </Card>
      </Stack>
    </Container>
  );
}
