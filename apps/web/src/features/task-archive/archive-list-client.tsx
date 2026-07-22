"use client";

import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";
import ArchiveOutlinedIcon from "@mui/icons-material/ArchiveOutlined";
import AutoStoriesOutlinedIcon from "@mui/icons-material/AutoStoriesOutlined";
import MenuBookOutlinedIcon from "@mui/icons-material/MenuBookOutlined";
import TextSnippetOutlinedIcon from "@mui/icons-material/TextSnippetOutlined";
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Pagination,
  Stack,
  Typography,
} from "@mui/material";
import { WorkbenchPageLayout } from "@/components/workbench-page-layout";
import { getArchiveList } from "@/lib/api";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { projectViewHref } from "@/lib/task-routes";
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

  const fetchPage = (targetPage: number) => {
    setLoading(true);
    void getArchiveList(targetPage, PAGE_SIZE)
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

  const handlePageChange = (_: React.ChangeEvent<unknown>, targetPage: number) => {
    setPage(targetPage);
  };

  const navigation = (
    <Card
      data-testid="archive-navigation"
      component="nav"
      aria-label="归档工作台导航"
      variant="outlined"
      sx={{ height: "100%", minHeight: 0, boxShadow: "none" }}
    >
      <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
        <Stack spacing={2.5} sx={{ height: "100%" }}>
          <Stack spacing={1}>
            <Stack direction="row" spacing={1} alignItems="center">
              <ArchiveOutlinedIcon color="primary" fontSize="small" aria-hidden="true" />
              <Typography variant="overline" color="text.secondary">
                作品库
              </Typography>
            </Stack>
            <Typography variant="h6">归档作品</Typography>
            <Typography variant="body2" color="text.secondary">
              已确认完成的作品会保留在这里，随时可回到章节与归档资料。
            </Typography>
          </Stack>

          <Box
            sx={{
              px: 1.5,
              py: 1.25,
              borderRadius: 2,
              bgcolor: "action.hover",
            }}
          >
            <Typography variant="caption" color="text.secondary">
              当前归档
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.25 }}>
              {loading ? "读取中" : `${formatNumber(total)} 部`}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              每页显示 {PAGE_SIZE} 部作品
            </Typography>
          </Box>

          <Stack spacing={1} sx={{ mt: "auto" }}>
            <Button
              component={Link}
              href="/"
              variant="outlined"
              startIcon={<ArrowBackRoundedIcon />}
              sx={{ minHeight: 44, justifyContent: "flex-start" }}
            >
              返回作品库
            </Button>
            <Typography variant="caption" color="text.secondary" sx={{ px: 0.5 }}>
              归档内容为只读副本，不会影响正在进行的任务。
            </Typography>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );

  const header = (
    <Box sx={{ px: { xs: 1.5, sm: 2.5, lg: 3 }, py: { xs: 1.5, sm: 2 } }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
        <Stack spacing={0.5} sx={{ minWidth: 0 }}>
          <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap" useFlexGap>
            <Typography id="archive-workbench-title" variant="h4" sx={{ overflowWrap: "anywhere" }}>
              归档列表
            </Typography>
            {!loading && total > 0 ? (
              <Typography variant="body2" color="text.secondary">
                共 {formatNumber(total)} 部
              </Typography>
            ) : null}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
            选择一部作品，查看其正文、章节索引、创作模型与执行记录。
          </Typography>
        </Stack>
        <Chip
          icon={<ArchiveOutlinedIcon />}
          label={loading ? "正在同步" : totalPages > 0 ? `第 ${page} / ${totalPages} 页` : "归档为空"}
          color="primary"
          variant="outlined"
          sx={{ flexShrink: 0, minHeight: 32 }}
        />
      </Stack>
    </Box>
  );

  const footer = totalPages > 1 ? (
    <Box
      component="nav"
      aria-label="归档列表分页"
      sx={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 1.5,
        minHeight: 68,
        px: { xs: 1, sm: 2 },
        py: 1,
        borderTop: 1,
        borderColor: "divider",
        bgcolor: "background.paper",
      }}
    >
      <Pagination
        count={totalPages}
        page={page}
        onChange={handlePageChange}
        shape="rounded"
        size="large"
        sx={{
          "& .MuiPagination-ul": { flexWrap: "wrap", justifyContent: "center" },
          "& .MuiPaginationItem-root": { minWidth: 44, minHeight: 44 },
        }}
      />
    </Box>
  ) : null;

  return (
    <WorkbenchPageLayout
      navigation={navigation}
      header={header}
      footer={footer}
      contentLabel="归档作品列表"
      testId="archive-workbench"
    >
      <Stack spacing={2.5} sx={{ minWidth: 0 }}>
        {error ? (
          <Alert
            severity="error"
            role="alert"
            action={
              <Button color="inherit" size="small" onClick={() => fetchPage(page)}>
                重试
              </Button>
            }
          >
            {error}
          </Alert>
        ) : null}

        {loading ? (
          <Stack spacing={1.5} role="status" aria-live="polite" aria-label="正在读取归档列表">
            {[1, 2, 3].map((index) => (
              <Card key={index} variant="outlined" sx={{ boxShadow: "none" }}>
                <CardContent sx={{ p: { xs: 1.5, sm: 2 }, "&:last-child": { pb: { xs: 1.5, sm: 2 } } }}>
                  <Stack spacing={1.25}>
                    <Box sx={{ height: 24, width: { xs: "70%", sm: "42%" }, bgcolor: "action.hover", borderRadius: 1 }} />
                    <Box sx={{ height: 16, width: "88%", bgcolor: "action.hover", borderRadius: 1 }} />
                    <Box sx={{ height: 16, width: { xs: "60%", sm: "35%" }, bgcolor: "action.hover", borderRadius: 1 }} />
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>
        ) : items.length ? (
          <Stack component="ul" data-testid="archive-list" spacing={1.5} sx={{ m: 0, p: 0, listStyle: "none", minWidth: 0 }}>
            {items.map((item) => {
              const taskTypeLabel = formatTaskTypeLabel({
                creativeMode: item.creative_mode,
                novelSize: item.novel_size,
                mode: item.mode,
              });
              const taskCreativeModel = item.creative_model_id || item.model_id || "未设置";

              return (
                <Card
                  key={item.task_id}
                  component="li"
                  data-testid="archive-card"
                  variant="outlined"
                  className="card-lift"
                  sx={{ minWidth: 0, boxShadow: "none" }}
                >
                  <CardContent sx={{ p: { xs: 1.5, sm: 2 }, "&:last-child": { pb: { xs: 1.5, sm: 2 } } }}>
                    <Box
                      sx={{
                        display: "grid",
                        gridTemplateColumns: { xs: "minmax(0, 1fr)", md: "minmax(0, 1.35fr) minmax(12.5rem, 0.85fr) auto" },
                        gap: { xs: 1.75, md: 2.5 },
                        alignItems: "start",
                        minWidth: 0,
                      }}
                    >
                      <Stack spacing={1.25} sx={{ minWidth: 0 }}>
                        <Stack spacing={0.5} sx={{ minWidth: 0 }}>
                          <Typography variant="h6" sx={{ overflowWrap: "anywhere", lineHeight: 1.35 }}>
                            {item.title}
                          </Typography>
                          <Typography color="text.secondary" sx={{ overflowWrap: "anywhere", lineHeight: 1.6 }}>
                            {item.summary || "暂无归档摘要。"}
                          </Typography>
                        </Stack>

                        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ minWidth: 0 }}>
                          <Chip icon={<MenuBookOutlinedIcon />} size="small" label={`${formatNumber(item.chapter_count)} 章`} />
                          <Chip icon={<TextSnippetOutlinedIcon />} size="small" label={`${formatNumber(item.word_count)} 字`} />
                          <Chip size="small" label={taskTypeLabel} variant="outlined" />
                        </Stack>
                      </Stack>

                      <Stack
                        spacing={0.75}
                        sx={{
                          minWidth: 0,
                          pl: { md: 2.5 },
                          borderLeft: { md: 1 },
                          borderColor: { md: "divider" },
                        }}
                      >
                        <Stack direction="row" spacing={0.75} alignItems="center">
                          <AutoStoriesOutlinedIcon color="action" fontSize="small" aria-hidden="true" />
                          <Typography variant="caption" color="text.secondary">
                            创作信息
                          </Typography>
                        </Stack>
                        <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
                          创作模型：{taskCreativeModel}
                        </Typography>
                        {item.last_action_model_id ? (
                          <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                            最近动作：{item.last_action_model_id}
                          </Typography>
                        ) : null}
                        <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                          归档更新：{formatDateTime(item.updated_at)}
                        </Typography>
                      </Stack>

                      <Button
                        component={Link}
                        href={projectViewHref(item.task_id, "archive")}
                        variant="outlined"
                        size="medium"
                        sx={{ minWidth: { md: 132 }, minHeight: 44, width: { xs: "100%", md: "auto" }, whiteSpace: "nowrap" }}
                      >
                        查看归档详情
                      </Button>
                    </Box>
                  </CardContent>
                </Card>
              );
            })}
          </Stack>
        ) : (
          <Card variant="outlined" sx={{ boxShadow: "none" }}>
            <CardContent sx={{ p: { xs: 2, sm: 3 }, "&:last-child": { pb: { xs: 2, sm: 3 } } }}>
              <Stack spacing={1.5} alignItems="flex-start">
                <ArchiveOutlinedIcon color="action" aria-hidden="true" />
                <Typography variant="h6">还没有归档作品</Typography>
                <Typography color="text.secondary">完成并确认归档后的作品，会在这里长期保留。</Typography>
                <Button component={Link} href="/" variant="outlined" startIcon={<ArrowBackRoundedIcon />} sx={{ minHeight: 44 }}>
                  返回作品库
                </Button>
              </Stack>
            </CardContent>
          </Card>
        )}
      </Stack>
    </WorkbenchPageLayout>
  );
}
