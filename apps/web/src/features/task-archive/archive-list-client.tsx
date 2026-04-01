"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Container,
  Pagination,
  Stack,
  Typography,
} from "@mui/material";
import { getArchiveList } from "@/lib/api";
import { ArchiveTaskSummary } from "@/lib/types";

const PAGE_SIZE = 10;

export default function ArchiveListClient() {
  const [items, setItems] = useState<ArchiveTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const fetchPage = (p: number) => {
    setLoading(true);
    void getArchiveList(p, PAGE_SIZE)
      .then((response) => {
        setItems(response.items ?? []);
        setTotal(response.total ?? 0);
        setTotalPages(response.total_pages ?? 0);
        setError("");
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "读取归档列表失败");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchPage(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const handlePageChange = (_: React.ChangeEvent<unknown>, p: number) => {
    setPage(p);
  };

  return (
    <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
    <Stack spacing={3} className="page-fade-in">
      {/* 标题 */}
      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={2}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", md: "center" }}
      >
        <Stack spacing={1}>
          <Stack direction="row" spacing={1.5} alignItems="baseline">
            <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              归档任务
            </Typography>
            {total > 0 && (
              <Typography variant="body2" color="text.secondary">
                共 {total} 条
              </Typography>
            )}
          </Stack>
          <Typography color="text.secondary">
            已完成任务会自动归档到这里，可查看正文、章节和事件尾流。
          </Typography>
        </Stack>
        <Button component={Link} href="/" variant="outlined" size="small">
          返回首页
        </Button>
      </Stack>

      {error ? <Alert severity="error">{error}</Alert> : null}

      {loading ? (
        <Stack spacing={2}>
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent>
                <Stack spacing={1.5}>
                  <Box sx={{ height: 24, width: "40%", bgcolor: "action.hover", borderRadius: 1 }} />
                  <Box sx={{ height: 16, width: "80%", bgcolor: "action.hover", borderRadius: 1 }} />
                  <Box sx={{ height: 14, width: "60%", bgcolor: "action.hover", borderRadius: 1 }} />
                </Stack>
              </CardContent>
            </Card>
          ))}
        </Stack>
      ) : items.length ? (
        <>
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
                    <Button
                      component={Link}
                      href={`/archive/${item.task_id}`}
                      variant="text"
                      sx={{ alignSelf: "flex-start", px: 0 }}
                    >
                      查看归档详情
                    </Button>
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>

          {totalPages > 1 && (
            <Box sx={{ display: "flex", justifyContent: "center" }}>
              <Pagination
                count={totalPages}
                page={page}
                onChange={handlePageChange}
                shape="rounded"
                size="large"
              />
            </Box>
          )}
        </>
      ) : (
        <Card>
          <CardContent>
            <Typography color="text.secondary">当前还没有可浏览的归档任务。</Typography>
          </CardContent>
        </Card>
      )}
    </Stack>
    </Container>
  );
}
