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
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  LinearProgress,
  Paper,
  Select,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  useMediaQuery,
  useTheme,
  alpha,
} from "@mui/material";
import {
  Computer as ComputerIcon,
  NavigateNext as NavigateNextIcon,
  Refresh as RefreshIcon,
  Settings as SettingsIcon,
} from "@mui/icons-material";
import {
  getModelCatalog,
  getProtocolSettings,
  getCurrentRagSyncJob,
  getRagSettings,
  getRagSyncJob,
  createRagSyncPlan,
  startRagSyncJob,
  setModelProtocol,
} from "@/lib/api";
import {
  ModelOption,
  RagSettingsStatus,
  RagSyncJob,
  RagSyncMode,
  RagSyncPlan,
  RagSyncResult,
} from "@/lib/types";
import { isGatewayBackedModel } from "@/lib/model-options.mjs";
import { normalizeModelOptions } from "@/lib/api";

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

function isTerminalRagJob(job: RagSyncJob | null) {
  return job?.status === "succeeded" || job?.status === "failed" || job?.status === "interrupted";
}

function formatRagMode(mode: RagSyncMode) {
  return mode === "full" ? "全量重建" : "增量同步";
}

export default function SettingsClient() {
  const [status, setStatus] = useState<RagSettingsStatus | null>(null);
  const [rebuildResult, setRebuildResult] = useState<RagSyncResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [startingMode, setStartingMode] = useState<RagSyncMode | null>(null);
  const [activeSyncJob, setActiveSyncJob] = useState<RagSyncJob | null>(null);
  const [pendingFullPlan, setPendingFullPlan] = useState<RagSyncPlan | null>(null);
  const [fullConfirmOpen, setFullConfirmOpen] = useState(false);
  const [incrementalRequirement, setIncrementalRequirement] = useState("");
  const [ragNotice, setRagNotice] = useState("");
  const [error, setError] = useState("");

  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState("");
  const [protocolMap, setProtocolMap] = useState<Record<string, string>>({});
  const [savingModelId, setSavingModelId] = useState<string | null>(null);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState("");
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError("");
      const nextStatus = await getRagSettings();
      setStatus(nextStatus);
      if (nextStatus.last_result) {
        setRebuildResult(nextStatus.last_result);
      }
      const currentJob = nextStatus.active_sync_job ?? await getCurrentRagSyncJob();
      setActiveSyncJob(currentJob);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取设置失败");
    } finally {
      setLoading(false);
    }
  };

  const loadModels = async () => {
    try {
      setModelsLoading(true);
      setModelsError("");
      const catalog = await getModelCatalog();
      const normalized = normalizeModelOptions(catalog.data ?? []);
      const gatewayModels = normalized.filter((m) => isGatewayBackedModel(m));
      setModels(gatewayModels);
      const settings = await getProtocolSettings();
      setProtocolMap(settings.overrides ?? {});
    } catch (reason) {
      setModelsError(reason instanceof Error ? reason.message : "读取模型列表失败");
    } finally {
      setModelsLoading(false);
    }
  };

  useEffect(() => {
    void loadStatus();
    void loadModels();
  }, []);

  useEffect(() => {
    const jobId = activeSyncJob?.job_id;
    if (!jobId || isTerminalRagJob(activeSyncJob)) {
      return undefined;
    }

    let disposed = false;
    const poll = async () => {
      try {
        const nextJob = await getRagSyncJob(jobId);
        if (disposed) {
          return;
        }
        setActiveSyncJob(nextJob);
        if (isTerminalRagJob(nextJob)) {
          if (nextJob.result) {
            setRebuildResult(nextJob.result);
          }
          if (nextJob.status === "succeeded") {
            setRagNotice(`${formatRagMode(nextJob.mode)}已完成。`);
          }
          if (nextJob.status === "failed" || nextJob.status === "interrupted") {
            setError(nextJob.error?.message ?? `${formatRagMode(nextJob.mode)}未完成，当前已发布索引未改变。`);
          }
        }
      } catch (reason) {
        if (!disposed) {
          setError(reason instanceof Error ? reason.message : "读取同步任务状态失败，请稍后重新获取状态。");
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), activeSyncJob.poll_after_ms ?? 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeSyncJob]);

  const handleProtocolChange = async (modelId: string, protocol: string) => {
    try {
      setSavingModelId(modelId);
      await setModelProtocol(modelId, protocol);
      setProtocolMap((prev) => ({ ...prev, [modelId]: protocol }));
      setSnackbarMessage(`已保存：${modelId} → ${protocol}`);
      setSnackbarOpen(true);
    } catch (reason) {
      const msg = reason instanceof Error ? reason.message : "保存协议失败";
      setModelsError(msg);
    } finally {
      setSavingModelId(null);
    }
  };

  const startSyncJob = async (plan: RagSyncPlan) => {
    try {
      setError("");
      setRagNotice("");
      const job = await startRagSyncJob({
        plan_id: plan.plan_id,
        mode: plan.mode,
        idempotency_key: crypto.randomUUID(),
        confirmation_token: plan.mode === "full" ? plan.confirmation?.token : undefined,
      });
      setActiveSyncJob(job);
      setRagNotice(`${formatRagMode(plan.mode)}已在后台启动，可离开此页面。`);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建同步任务失败");
      return false;
    }
  };

  const handleIncrementalSync = async () => {
    try {
      setStartingMode("incremental");
      setError("");
      setRagNotice("");
      setIncrementalRequirement("");
      const plan = await createRagSyncPlan("incremental");
      if (plan.state === "noop") {
        setRagNotice("未发现需要同步的来源，当前索引已是最新状态。");
        return;
      }
      if (!plan.can_start || plan.state === "full_rebuild_required") {
        setIncrementalRequirement(plan.reason ?? "当前索引无法安全执行增量同步，请显式执行全量重建。");
        return;
      }
      await startSyncJob(plan);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建增量同步预检失败");
    } finally {
      setStartingMode(null);
    }
  };

  const handlePrepareFullSync = async () => {
    try {
      setStartingMode("full");
      setError("");
      setRagNotice("");
      const plan = await createRagSyncPlan("full");
      if (!plan.can_start || !plan.confirmation?.token) {
        setError(plan.reason ?? "无法创建全量重建确认，请重新获取状态。");
        return;
      }
      setPendingFullPlan(plan);
      setFullConfirmOpen(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建全量重建预检失败");
    } finally {
      setStartingMode(null);
    }
  };

  const handleConfirmFullSync = async () => {
    if (!pendingFullPlan) {
      return;
    }
    setStartingMode("full");
    try {
      const started = await startSyncJob(pendingFullPlan);
      if (started) {
        setFullConfirmOpen(false);
        setPendingFullPlan(null);
      }
    } finally {
      setStartingMode(null);
    }
  };

  const hasActiveSyncJob = Boolean(activeSyncJob && !isTerminalRagJob(activeSyncJob));
  const activeProgressValue = typeof activeSyncJob?.progress === "number"
    ? activeSyncJob.progress
    : activeSyncJob?.progress?.total
      ? Math.min(100, Math.round(((activeSyncJob.progress.completed ?? 0) / activeSyncJob.progress.total) * 100))
      : undefined;
  const activeProgressTotal = typeof activeSyncJob?.progress === "object"
    ? activeSyncJob.progress?.total
    : undefined;
  const activeProgressCompleted = typeof activeSyncJob?.progress === "object"
    ? activeSyncJob.progress?.completed
    : undefined;

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

        {error ? <Alert severity="error" role="alert">{error}</Alert> : null}

        <Card>
          <CardContent>
            {loading ? (
              <Stack direction="row" spacing={1.5} alignItems="center" role="status" aria-live="polite">
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

                {status?.sync_capability?.incremental_ready === false ? (
                  <Alert severity="warning" role="status">
                    {status.sync_capability.reason ?? "当前索引需要显式全量重建后才能使用增量同步。"}
                  </Alert>
                ) : null}

                {incrementalRequirement ? (
                  <Alert severity="warning" role="status">
                    {incrementalRequirement}
                  </Alert>
                ) : null}

                {ragNotice ? <Alert severity="info" role="status">{ragNotice}</Alert> : null}

                <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                  <Box
                    sx={(theme) => ({
                      flex: 1,
                      minWidth: 0,
                      p: 2,
                      borderRadius: 3,
                      backgroundColor: alpha(theme.palette.primary.main, 0.06),
                      border: "1px solid",
                      borderColor: "primary.light",
                    })}
                  >
                    <Stack spacing={1.5} alignItems="flex-start">
                      <Typography variant="subtitle1">增量同步</Typography>
                      <Typography variant="body2" color="text.secondary">
                        比较来源指纹，只嵌入新增或变更资料，并移除已删除来源；不会隐式执行全量重建。
                      </Typography>
                      <Button
                        data-testid="rag-incremental-sync"
                        variant="contained"
                        startIcon={startingMode === "incremental" ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                        disabled={Boolean(startingMode) || hasActiveSyncJob || status?.sync_capability?.incremental_ready === false}
                        onClick={() => void handleIncrementalSync()}
                        sx={{ minHeight: 44, width: { xs: "100%", sm: "auto" } }}
                      >
                        {startingMode === "incremental" ? "正在预检..." : "增量同步"}
                      </Button>
                    </Stack>
                  </Box>

                  <Box
                    sx={(theme) => ({
                      flex: 1,
                      minWidth: 0,
                      p: 2,
                      borderRadius: 3,
                      backgroundColor: alpha(theme.palette.warning.main, 0.07),
                      border: "1px solid",
                      borderColor: "warning.light",
                    })}
                  >
                    <Stack spacing={1.5} alignItems="flex-start">
                      <Typography variant="subtitle1">全量重建</Typography>
                      <Typography variant="body2" color="text.secondary">
                        重新嵌入全部资料，适用于首次初始化、索引修复或模型与分块规则变化；耗时较长。
                      </Typography>
                      <Button
                        data-testid="rag-full-rebuild"
                        color="warning"
                        variant="outlined"
                        startIcon={startingMode === "full" ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                        disabled={Boolean(startingMode) || hasActiveSyncJob}
                        onClick={() => void handlePrepareFullSync()}
                        sx={{ minHeight: 44, width: { xs: "100%", sm: "auto" } }}
                      >
                        {startingMode === "full" ? "正在预检..." : "全量重建"}
                      </Button>
                    </Stack>
                  </Box>
                </Stack>

                {activeSyncJob ? (
                  <Card variant="outlined" data-testid="rag-sync-job" sx={{ borderRadius: 3 }}>
                    <CardContent sx={{ p: 2.5, "&:last-child": { pb: 2.5 } }}>
                      <Stack spacing={1.25} role="status" aria-live="polite">
                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                          <Typography variant="subtitle1">
                            {isTerminalRagJob(activeSyncJob) ? `${formatRagMode(activeSyncJob.mode)}已结束` : `正在后台${formatRagMode(activeSyncJob.mode)}`}
                          </Typography>
                          <Chip
                            size="small"
                            color={activeSyncJob.status === "succeeded" ? "success" : activeSyncJob.status === "failed" || activeSyncJob.status === "interrupted" ? "error" : "info"}
                            label={activeSyncJob.status === "queued" ? "等待执行" : activeSyncJob.status === "running" ? "进行中" : activeSyncJob.status === "succeeded" ? "已完成" : activeSyncJob.status === "interrupted" ? "已中断" : "失败"}
                          />
                        </Stack>
                        {!isTerminalRagJob(activeSyncJob) ? (
                          <>
                            <Typography variant="body2" color="text.secondary">
                              {activeSyncJob.phase_label ?? activeSyncJob.phase} · 同步在后台继续运行，可离开此页面。
                            </Typography>
                            <LinearProgress
                              variant={typeof activeProgressValue === "number" ? "determinate" : "indeterminate"}
                              value={activeProgressValue}
                            />
                            {activeProgressTotal ? (
                              <Typography variant="caption" color="text.secondary">
                                已处理 {activeProgressCompleted ?? 0} / {activeProgressTotal}
                              </Typography>
                            ) : null}
                          </>
                        ) : null}
                        {activeSyncJob.error?.message ? <Alert severity="error">{activeSyncJob.error.message}</Alert> : null}
                      </Stack>
                    </CardContent>
                  </Card>
                ) : null}

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
                          {rebuildResult.sync_mode ? (
                            <Typography variant="body2" color="text.secondary">
                              同步方式：{rebuildResult.sync_mode === "full" ? "全量构建" : rebuildResult.sync_mode === "noop" ? "无需变更" : "增量同步"}
                              {typeof rebuildResult.embedded_documents === "number" ? ` · 本次嵌入：${rebuildResult.embedded_documents}` : ""}
                              {typeof rebuildResult.reused_documents === "number" ? ` · 复用：${rebuildResult.reused_documents}` : ""}
                            </Typography>
                          ) : null}
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
                      还没有执行过索引同步。
                    </Typography>
                  )}
                </Stack>
              </Stack>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} alignItems="center">
                <ComputerIcon color="primary" />
                <Typography variant="h6">模型协议配置</Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary">
                为 Gateway 后端模型指定请求协议（OpenAI 或 Anthropic）。仅列出 source 包含 gateway 的模型。
              </Typography>

              {modelsLoading ? (
                <Stack direction="row" spacing={1.5} alignItems="center" role="status" aria-live="polite">
                  <CircularProgress size={20} />
                  <Typography>正在读取模型列表...</Typography>
                </Stack>
              ) : modelsError ? (
                <Alert severity="error" role="alert">{modelsError}</Alert>
              ) : models.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  暂无可用模型
                </Typography>
              ) : isDesktop ? (
                /* 桌面端：表格 */
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>显示名称</TableCell>
                        <TableCell>模型 ID</TableCell>
                        <TableCell>当前协议</TableCell>
                        <TableCell>修改协议</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {models.map((model) => {
                        const currentProtocol = protocolMap[model.id] || model.metadata?.protocol || "未配置";
                        return (
                          <TableRow key={model.id}>
                            <TableCell>{model.display_name || model.id}</TableCell>
                            <TableCell sx={{ fontFamily: "monospace", fontSize: "0.8rem" }}>{model.id}</TableCell>
                            <TableCell>
                              <Chip
                                size="small"
                                label={currentProtocol}
                                color={currentProtocol === "openai" ? "primary" : currentProtocol === "anthropic" ? "secondary" : "default"}
                              />
                            </TableCell>
                            <TableCell>
                              <FormControl size="small" sx={{ minWidth: 140 }} disabled={savingModelId === model.id}>
                                <InputLabel id={`protocol-label-${model.id}`}>协议</InputLabel>
                                <Select
                                  labelId={`protocol-label-${model.id}`}
                                  value={currentProtocol === "未配置" ? "" : currentProtocol}
                                  label="协议"
                                  onChange={(e) => handleProtocolChange(model.id, e.target.value)}
                                  endAdornment={
                                    savingModelId === model.id ? (
                                      <CircularProgress size={16} sx={{ mr: 1 }} />
                                    ) : null
                                  }
                                >
                                  <MenuItem value="openai">OpenAI</MenuItem>
                                  <MenuItem value="anthropic">Anthropic</MenuItem>
                                </Select>
                              </FormControl>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              ) : (
                /* 移动端：键值卡片列表 */
                <Stack spacing={1.5}>
                  {models.map((model) => {
                    const currentProtocol = protocolMap[model.id] || model.metadata?.protocol || "未配置";
                    return (
                      <Card key={model.id} variant="outlined" sx={{ borderRadius: 2 }}>
                        <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
                          <Stack spacing={1.5}>
                            <Stack direction="row" justifyContent="space-between" alignItems="center">
                              <Typography variant="subtitle2" sx={{ fontWeight: 600, overflowWrap: "anywhere", flex: 1 }}>
                                {model.display_name || model.id}
                              </Typography>
                              <Chip
                                size="small"
                                label={currentProtocol}
                                color={currentProtocol === "openai" ? "primary" : currentProtocol === "anthropic" ? "secondary" : "default"}
                              />
                            </Stack>
                            <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace", overflowWrap: "anywhere" }}>
                              {model.id}
                            </Typography>
                            <FormControl size="small" fullWidth disabled={savingModelId === model.id}>
                              <InputLabel id={`protocol-label-mobile-${model.id}`}>修改协议</InputLabel>
                              <Select
                                labelId={`protocol-label-mobile-${model.id}`}
                                value={currentProtocol === "未配置" ? "" : currentProtocol}
                                label="修改协议"
                                onChange={(e) => handleProtocolChange(model.id, e.target.value)}
                                endAdornment={
                                  savingModelId === model.id ? (
                                    <CircularProgress size={16} sx={{ mr: 1 }} />
                                  ) : null
                                }
                              >
                                <MenuItem value="openai">OpenAI</MenuItem>
                                <MenuItem value="anthropic">Anthropic</MenuItem>
                              </Select>
                            </FormControl>
                          </Stack>
                        </CardContent>
                      </Card>
                    );
                  })}
                </Stack>
              )}
            </Stack>
          </CardContent>
        </Card>
      </Stack>

      <Dialog
        open={fullConfirmOpen}
        fullWidth
        maxWidth="sm"
        aria-labelledby="rag-full-rebuild-title"
        aria-describedby="rag-full-rebuild-description"
        onClose={() => {
          if (!startingMode) {
            setFullConfirmOpen(false);
            setPendingFullPlan(null);
          }
        }}
      >
        <DialogTitle id="rag-full-rebuild-title">确认全量重建 RAG 索引？</DialogTitle>
        <DialogContent>
          <Stack spacing={2}>
            <DialogContentText id="rag-full-rebuild-description">
              将重新分块并嵌入全部资料，耗时可能较长。新索引通过校验前，当前已发布索引会继续提供查询服务。
            </DialogContentText>
            <Alert severity="warning">
              仅在首次初始化、索引需要修复、模型或分块规则变化时使用。普通资料更新请选择“增量同步”。
            </Alert>
            {pendingFullPlan?.summary ? (
              <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                预检：扫描 {pendingFullPlan.summary.scanned_sources ?? 0} 个来源 · 预计嵌入 {pendingFullPlan.summary.embedded_documents ?? 0} 个文档
              </Typography>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1, flexWrap: "wrap" }}>
          <Button
            autoFocus
            disabled={startingMode === "full"}
            onClick={() => {
              setFullConfirmOpen(false);
              setPendingFullPlan(null);
            }}
            sx={{ minHeight: 44 }}
          >
            取消
          </Button>
          <Button
            color="warning"
            variant="contained"
            disabled={startingMode === "full"}
            onClick={() => void handleConfirmFullSync()}
            startIcon={startingMode === "full" ? <CircularProgress size={16} color="inherit" /> : undefined}
            sx={{ minHeight: 44 }}
          >
            确认全量重建
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbarOpen}
        autoHideDuration={3000}
        onClose={() => setSnackbarOpen(false)}
        message={snackbarMessage}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </Container>
  );
}
