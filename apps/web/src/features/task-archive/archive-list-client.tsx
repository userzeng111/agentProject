"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Container,
  Stack,
  Typography,
} from "@mui/material";
import { getArchiveList } from "@/lib/api";
import { ArchiveTaskSummary } from "@/lib/types";

export default function ArchiveListClient() {
  const [items, setItems] = useState<ArchiveTaskSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void getArchiveList()
      .then((response) => {
        setItems(response.items ?? []);
        setError("");
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "读取归档列表失败");
      });
  }, []);

  return (
    <Container maxWidth="lg" sx={{ py: 6 }}>
      <Stack spacing={3}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between">
          <Stack spacing={1}>
            <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              归档任务
            </Typography>
            <Typography color="text.secondary">
              已完成任务会自动归档到这里，可查看正文、章节和事件尾流。
            </Typography>
          </Stack>
          <Button component={Link} href="/" variant="outlined">
            返回首页
          </Button>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        {items.length ? (
          <Stack spacing={2}>
            {items.map((item) => (
              <Card key={item.task_id} variant="outlined" sx={{ borderRadius: 3 }}>
                <CardContent>
                  <Stack spacing={1.5}>
                    <Typography variant="h6">{item.title}</Typography>
                    <Typography color="text.secondary">{item.summary}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      模式：{item.mode} · 模型：{item.model_id || "默认模型"} · 更新时间：
                      {new Date(item.updated_at).toLocaleString()}
                    </Typography>
                    <Button component={Link} href={`/archive/${item.task_id}`} sx={{ alignSelf: "flex-start", px: 0 }}>
                      查看归档详情
                    </Button>
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>
        ) : (
          <Card sx={{ borderRadius: 4 }}>
            <CardContent>
              <Typography color="text.secondary">当前还没有可浏览的归档任务。</Typography>
            </CardContent>
          </Card>
        )}
      </Stack>
    </Container>
  );
}
