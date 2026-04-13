"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Container,
  Divider,
  Stack,
  Typography,
} from "@mui/material";
import { NavigateNext as NavigateNextIcon, Refresh as RefreshIcon, Settings as SettingsIcon } from "@mui/icons-material";
import { getRagSettings, rebuildRagLibrary } from "@/lib/api";
import { RagSettingsStatus, RagSyncResult } from "@/lib/types";

function formatDateTime(value?: string) {
  if (!value) {
    return "未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN");
}

export default function SettingsClient() {
  const [status, setStatus] = useState<RagSettingsStatus | null>(null);
  const [rebuildResult, setRebuildResult] = useState<RagSyncResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [error, setError] = useState("");

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError("");
      const nextStatus = await getRagSettings();
      setStatus(nextStatus);
      setRebuildResult(nextStatus.last_result ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取设置失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  const handleRebuild = async () => {
    // eslint-disable-next-line no-alert
    if (!window.confirm("确认全量扫描示例小说与归档小说，并重建小说专用 RAG 索引吗？")) {
      return;
    }

    try {
      setRebuilding(true);
      setError("");
      const result = await rebuildRagLibrary();
      setRebuildResult(result);
      await loadStatus();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "重建索引失败");
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
      <Stack spacing={3} className="page-fade-in">
        <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
          <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
            <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
              首页
            </Typography>
          </Link>
          <Typography variant="body2">设置</Typography>
        </Breadcrumbs>

        <Stack spacing={1}>
          <Stack direction="row" spacing={1} alignItems="center">
            <SettingsIcon color="primary" />
            <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
              设置
            </Typography>
          </Stack>
          <Typography color="text.secondary">
            管理小说专用 RAG 数据库，并手动同步新加入的示例小说和归档小说文档。
          </Typography>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        <Card>
          <CardContent>
            {loading ? (
              <Stack direction="row" spacing={1.5} alignItems="center">
                <CircularProgress size={20} />
                <Typography>正在读取当前数据库状态...</Typography>
              </Stack>
            ) : (
              <Stack spacing={2}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                  <Box>
                    <Typography variant="h6">小说 RAG 数据库</Typography>
                    <Typography variant="body2" color="text.secondary">
                      当前聊天问答和小说任务流默认都读取这套语料库。
                    </Typography>
                  </Box>
                  <Chip
                    color={status?.available ? "success" : "default"}
                    variant={status?.available ? "filled" : "outlined"}
                    label={status?.available ? "数据库可用" : "尚未构建"}
                  />
                </Stack>

                <Divider />

                <Stack spacing={1}>
                  <Typography variant="subtitle2">数据库路径</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {status?.library_dir || "未配置"}
                  </Typography>
                </Stack>

                <Stack spacing={1}>
                  <Typography variant="subtitle2">语料来源</Typography>
                  <Stack spacing={1}>
                    {(status?.sources ?? []).map((source) => (
                      <Typography key={source} variant="body2" color="text.secondary">
                        {source}
                      </Typography>
                    ))}
                  </Stack>
                </Stack>

                <Box
                  sx={{
                    p: 2,
                    borderRadius: 3,
                    backgroundColor: "rgba(29, 42, 39, 0.04)",
                    border: "1px solid",
                    borderColor: "divider",
                  }}
                >
                  <Stack spacing={2}>
                    <Typography variant="subtitle1">全量重建索引</Typography>
                    <Typography variant="body2" color="text.secondary">
                      扫描 `exampleIndexData/*.txt` 与 `tasklog/archive/*/artifacts/final.md + outline.md`，并重建小说专用索引。
                    </Typography>
                    <Box>
                      <Button
                        variant="contained"
                        startIcon={rebuilding ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                        disabled={rebuilding}
                        onClick={handleRebuild}
                      >
                        {rebuilding ? "正在扫描并重建..." : "全量重建索引"}
                      </Button>
                    </Box>
                  </Stack>
                </Box>

                <Stack spacing={1}>
                  <Typography variant="subtitle2">最近一次同步结果</Typography>
                  {rebuildResult ? (
                    <Card variant="outlined" sx={{ borderRadius: 3 }}>
                      <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                        <Stack spacing={1.25}>
                          <Typography color={rebuildResult.success ? "success.main" : "error.main"}>
                            {rebuildResult.message}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            扫描文件：{rebuildResult.scanned_files} · 入库文档：{rebuildResult.indexed_documents} · 耗时：{rebuildResult.duration_ms} ms
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            输出目录：{rebuildResult.output_dir}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            最近结果时间：{formatDateTime(rebuildResult.finished_at)}
                          </Typography>
                          {rebuildResult.warnings?.length ? (
                            <Alert severity="warning">
                              {rebuildResult.warnings.join("；")}
                            </Alert>
                          ) : null}
                        </Stack>
                      </CardContent>
                    </Card>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      还没有执行过全量重建。
                    </Typography>
                  )}
                </Stack>
              </Stack>
            )}
          </CardContent>
        </Card>
      </Stack>
    </Container>
  );
}
