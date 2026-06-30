"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Pagination,
  Stack,
  Typography,
} from "@mui/material";
import { getArchiveList } from "@/lib/api";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { archiveDetailHref } from "@/lib/task-routes";
import { ArchiveTaskSummary } from "@/lib/types";

const PAGE_SIZE = 10;

function formatDateTime(value?: string | null): string {
  if (!value) return "未记录";
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return value;
  }
}

function formatNumber(value?: number | null): string {
  return Number(value ?? 0).toLocaleString("zh-CN");
}

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
      <Stack spacing={3} className="page-fade-in" sx={{ minWidth: 0 }}>
        {/* 标题 */}
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", md: "center" }}
          sx={{ minWidth: 0 }}
        >
          <Stack spacing={1} sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={1.5} alignItems="baseline" flexWrap="wrap" useFlexGap sx={{ minWidth: 0 }}>
              <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)", overflowWrap: "anywhere" }}>
                归档任务
              </Typography>
              {total > 0 && (
                <Typography variant="body2" color="text.secondary">
                  共 {total} 条
                </Typography>
              )}
            </Stack>
            <Typography color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
              已完成作品会自动归档到这里，可快速浏览正文、章节、模型和事件尾流。
            </Typography>
          </Stack>
          <Button component={Link} href="/" variant="outlined" size="small" sx={{ flexShrink: 0 }}>
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
              {items.map((item) => {
                const taskTypeLabel = formatTaskTypeLabel({
                  creativeMode: item.creative_mode,
                  novelSize: item.novel_size,
                  mode: item.mode,
                });
                const defaultModel = item.default_model_id || item.model_id || "默认模型";
                return (
                  <Card key={item.task_id} data-testid="archive-card" variant="outlined" sx={{ borderRadius: 2, minWidth: 0 }}>
                    <CardContent>
                      <Stack spacing={2} sx={{ minWidth: 0 }}>
                        <Stack
                          direction={{ xs: "column", sm: "row" }}
                          spacing={1.5}
                          justifyContent="space-between"
                          alignItems={{ xs: "flex-start", sm: "flex-start" }}
                          sx={{ minWidth: 0 }}
                        >
                          <Stack spacing={0.75} sx={{ minWidth: 0, flex: 1 }}>
                            <Typography variant="h6" sx={{ overflowWrap: "anywhere" }}>
                              {item.title}
                            </Typography>
                            <Typography color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                              {item.summary || "暂无归档摘要。"}
                            </Typography>
                          </Stack>
                          <Button
                            component={Link}
                            href={archiveDetailHref(item.task_id)}
                            variant="outlined"
                            size="small"
                            sx={{ flexShrink: 0 }}
                          >
                            查看归档详情
                          </Button>
                        </Stack>

                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ minWidth: 0 }}>
                          <Chip size="small" label={`章节：${formatNumber(item.chapter_count)}`} />
                          <Chip size="small" label={`字数：${formatNumber(item.word_count)}`} />
                          <Chip size="small" label={taskTypeLabel} variant="outlined" />
                        </Stack>

                        <Stack spacing={0.5} sx={{ minWidth: 0 }}>
                          <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                            任务默认模型：{defaultModel}
                          </Typography>
                          {item.last_action_model_id ? (
                            <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                              最近一次动作模型：{item.last_action_model_id}
                            </Typography>
                          ) : null}
                          <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                            更新时间：{formatDateTime(item.updated_at)}
                          </Typography>
                        </Stack>
                      </Stack>
                    </CardContent>
                  </Card>
                );
              })}
            </Stack>

            {totalPages > 1 && (
              <Box sx={{ display: "flex", justifyContent: "center", minWidth: 0 }}>
                <Pagination count={totalPages} page={page} onChange={handlePageChange} shape="rounded" size="large" />
              </Box>
            )}
          </>
        ) : (
          <Card>
            <CardContent>
              <Stack spacing={1.5}>
                <Typography color="text.secondary">当前还没有可浏览的归档任务。</Typography>
                <Button component={Link} href="/" variant="outlined" size="small" sx={{ alignSelf: "flex-start" }}>
                  返回首页
                </Button>
              </Stack>
            </CardContent>
          </Card>
        )}
      </Stack>
    </Container>
  );
}
