"use client";

import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import StorageOutlinedIcon from "@mui/icons-material/StorageOutlined";
import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  LinearProgress,
  Stack,
  Typography,
} from "@mui/material";
import { createRagSyncPlan, getCurrentRagSyncJob, getRagSettings, getRagSyncJob, startRagSyncJob } from "@/lib/api";
import { RagSettingsStatus, RagSyncJob, RagSyncMode, RagSyncPlan, RagSyncResult } from "@/lib/types";
import { SettingsShell } from "./settings-shell";

function formatDateTime(value?: string) {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function isTerminalRagJob(job: RagSyncJob | null) {
  return job?.status === "succeeded" || job?.status === "failed" || job?.status === "interrupted";
}

function formatRagMode(mode: RagSyncMode) {
  return mode === "full" ? "全量重建" : "增量同步";
}

function jobStatusLabel(job: RagSyncJob) {
  if (job.status === "queued") return "等待执行";
  if (job.status === "running") return "进行中";
  if (job.status === "succeeded") return "已完成";
  if (job.status === "interrupted") return "已中断";
  return "失败";
}

export default function RagSettingsClient() {
  const [status, setStatus] = useState<RagSettingsStatus | null>(null);
  const [rebuildResult, setRebuildResult] = useState<RagSyncResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [startingMode, setStartingMode] = useState<RagSyncMode | null>(null);
  const [activeSyncJob, setActiveSyncJob] = useState<RagSyncJob | null>(null);
  const [pendingFullPlan, setPendingFullPlan] = useState<RagSyncPlan | null>(null);
  const [fullConfirmOpen, setFullConfirmOpen] = useState(false);
  const [incrementalRequirement, setIncrementalRequirement] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError("");
      const nextStatus = await getRagSettings();
      setStatus(nextStatus);
      setRebuildResult(nextStatus.last_result ?? null);
      const currentJob = nextStatus.active_sync_job ?? await getCurrentRagSyncJob();
      setActiveSyncJob(currentJob);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取 RAG 状态失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  useEffect(() => {
    const jobId = activeSyncJob?.job_id;
    if (!jobId || isTerminalRagJob(activeSyncJob)) return undefined;

    let disposed = false;
    const poll = async () => {
      try {
        const nextJob = await getRagSyncJob(jobId);
        if (disposed) return;
        setActiveSyncJob(nextJob);
        if (!isTerminalRagJob(nextJob)) return;
        if (nextJob.result) setRebuildResult(nextJob.result);
        if (nextJob.status === "succeeded") setNotice(`${formatRagMode(nextJob.mode)}已完成。`);
        if (nextJob.status === "failed" || nextJob.status === "interrupted") {
          setError(nextJob.error?.message ?? `${formatRagMode(nextJob.mode)}未完成，当前已发布索引未改变。`);
        }
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : "读取同步任务状态失败，请稍后刷新。");
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), activeSyncJob.poll_after_ms ?? 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeSyncJob]);

  const startSyncJob = async (plan: RagSyncPlan) => {
    try {
      setError("");
      setNotice("");
      const job = await startRagSyncJob({
        plan_id: plan.plan_id,
        mode: plan.mode,
        idempotency_key: crypto.randomUUID(),
        confirmation_token: plan.mode === "full" ? plan.confirmation?.token : undefined,
      });
      setActiveSyncJob(job);
      setNotice(`${formatRagMode(plan.mode)}已在后台启动，可离开此页面。`);
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
      setNotice("");
      setIncrementalRequirement("");
      const plan = await createRagSyncPlan("incremental");
      if (plan.state === "noop") {
        setNotice("未发现需要同步的来源，当前索引已是最新状态。");
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
      setNotice("");
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
    if (!pendingFullPlan) return;
    setStartingMode("full");
    try {
      if (await startSyncJob(pendingFullPlan)) {
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
  const activeProgressTotal = typeof activeSyncJob?.progress === "object" ? activeSyncJob.progress?.total : undefined;
  const activeProgressCompleted = typeof activeSyncJob?.progress === "object" ? activeSyncJob.progress?.completed : undefined;

  return (
    <SettingsShell section="rag">
      {error ? <Alert severity="error" role="alert" action={<Button color="inherit" size="small" onClick={() => void loadStatus()}>刷新</Button>}>{error}</Alert> : null}
      {incrementalRequirement ? <Alert severity="warning" role="status">{incrementalRequirement}</Alert> : null}
      {notice ? <Alert severity="info" role="status">{notice}</Alert> : null}

      <Card variant="outlined" sx={{ boxShadow: "none" }}>
        <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
          {loading ? (
            <Stack direction="row" spacing={1.5} alignItems="center" role="status" aria-live="polite">
              <CircularProgress size={20} />
              <Typography>正在读取当前数据库状态…</Typography>
            </Stack>
          ) : (
            <Stack spacing={2.25}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <StorageOutlinedIcon color="primary" aria-hidden="true" />
                  <Stack spacing={0.25}>
                    <Typography variant="h6">索引状态</Typography>
                    <Typography variant="body2" color="text.secondary">聊天问答和小说任务共用这套语料库。</Typography>
                  </Stack>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Chip color={status?.available ? "success" : "default"} variant={status?.available ? "filled" : "outlined"} label={status?.available ? "数据库可用" : "尚未构建"} />
                  <Button variant="text" size="small" onClick={() => void loadStatus()} disabled={loading} startIcon={<RefreshRoundedIcon />}>刷新</Button>
                </Stack>
              </Stack>

              <Divider />

              <Stack spacing={1.5}>
                <Stack spacing={0.5}>
                  <Typography variant="subtitle2">数据库路径</Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>{status?.library_dir || "未配置"}</Typography>
                </Stack>
                <Stack spacing={0.5}>
                  <Typography variant="subtitle2">语料来源</Typography>
                  {(status?.sources ?? []).length ? (
                    <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2.5 }}>
                      {(status?.sources ?? []).map((source) => <Typography key={source} component="li" variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>{source}</Typography>)}
                    </Stack>
                  ) : <Typography variant="body2" color="text.secondary">暂无已配置来源。</Typography>}
                </Stack>
              </Stack>

              {status?.sync_capability?.incremental_ready === false ? <Alert severity="warning">{status.sync_capability.reason ?? "当前索引需要显式全量重建后才能使用增量同步。"}</Alert> : null}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Card variant="outlined" sx={{ flex: 1, minWidth: 0, borderColor: "primary.light", boxShadow: "none" }}>
          <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
            <Stack spacing={1.5} alignItems="flex-start">
              <Typography variant="h6">增量同步</Typography>
              <Typography variant="body2" color="text.secondary">
                比较来源指纹，只嵌入新增或变更资料，并移除已删除来源；不会隐式执行全量重建。
              </Typography>
              <Button
                data-testid="rag-incremental-sync"
                variant="contained"
                startIcon={startingMode === "incremental" ? <CircularProgress size={16} color="inherit" /> : <RefreshRoundedIcon />}
                disabled={Boolean(startingMode) || hasActiveSyncJob || status?.sync_capability?.incremental_ready === false}
                onClick={() => void handleIncrementalSync()}
                sx={{ minHeight: 44, width: { xs: "100%", sm: "auto" } }}
              >
                {startingMode === "incremental" ? "正在预检…" : "增量同步"}
              </Button>
            </Stack>
          </CardContent>
        </Card>

        <Card variant="outlined" sx={{ flex: 1, minWidth: 0, borderColor: "warning.light", boxShadow: "none" }}>
          <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
            <Stack spacing={1.5} alignItems="flex-start">
              <Typography variant="h6">全量重建</Typography>
              <Typography variant="body2" color="text.secondary">
                重新嵌入全部资料，适用于首次初始化、索引修复或模型与分块规则变化；耗时较长。
              </Typography>
              <Button
                data-testid="rag-full-rebuild"
                color="warning"
                variant="outlined"
                startIcon={startingMode === "full" ? <CircularProgress size={16} color="inherit" /> : <RefreshRoundedIcon />}
                disabled={Boolean(startingMode) || hasActiveSyncJob}
                onClick={() => void handlePrepareFullSync()}
                sx={{ minHeight: 44, width: { xs: "100%", sm: "auto" } }}
              >
                {startingMode === "full" ? "正在预检…" : "全量重建"}
              </Button>
            </Stack>
          </CardContent>
        </Card>
      </Stack>

      {activeSyncJob ? (
        <Card variant="outlined" data-testid="rag-sync-job" sx={{ boxShadow: "none" }}>
          <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
            <Stack spacing={1.25} role="status" aria-live="polite">
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                <Typography variant="h6">{isTerminalRagJob(activeSyncJob) ? `${formatRagMode(activeSyncJob.mode)}已结束` : `正在后台${formatRagMode(activeSyncJob.mode)}`}</Typography>
                <Chip size="small" color={activeSyncJob.status === "succeeded" ? "success" : activeSyncJob.status === "failed" || activeSyncJob.status === "interrupted" ? "error" : "info"} label={jobStatusLabel(activeSyncJob)} />
              </Stack>
              {!isTerminalRagJob(activeSyncJob) ? (
                <>
                  <Typography variant="body2" color="text.secondary">{activeSyncJob.phase_label ?? activeSyncJob.phase} · 同步在后台继续运行，可离开此页面。</Typography>
                  <LinearProgress variant={typeof activeProgressValue === "number" ? "determinate" : "indeterminate"} value={activeProgressValue} />
                  {activeProgressTotal ? <Typography variant="caption" color="text.secondary">已处理 {activeProgressCompleted ?? 0} / {activeProgressTotal}</Typography> : null}
                </>
              ) : null}
              {activeSyncJob.error?.message ? <Alert severity="error">{activeSyncJob.error.message}</Alert> : null}
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      <Card variant="outlined" sx={{ boxShadow: "none" }}>
        <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
          <Stack spacing={1.25}>
            <Typography variant="h6">最近一次同步结果</Typography>
            {rebuildResult ? (
              <Stack spacing={0.75}>
                <Typography color={rebuildResult.success ? "success.main" : "error.main"}>{rebuildResult.message}</Typography>
                <Typography variant="body2" color="text.secondary">扫描文件：{rebuildResult.scanned_files} · 入库文档：{rebuildResult.indexed_documents} · 耗时：{rebuildResult.duration_ms} ms</Typography>
                {rebuildResult.sync_mode ? <Typography variant="body2" color="text.secondary">同步方式：{rebuildResult.sync_mode === "full" ? "全量构建" : rebuildResult.sync_mode === "noop" ? "无需变更" : "增量同步"}{typeof rebuildResult.embedded_documents === "number" ? ` · 本次嵌入：${rebuildResult.embedded_documents}` : ""}{typeof rebuildResult.reused_documents === "number" ? ` · 复用：${rebuildResult.reused_documents}` : ""}</Typography> : null}
                <Typography variant="body2" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>输出目录：{rebuildResult.output_dir}</Typography>
                <Typography variant="body2" color="text.secondary">最近结果时间：{formatDateTime(rebuildResult.finished_at)}</Typography>
                {rebuildResult.warnings?.length ? <Alert severity="warning">{rebuildResult.warnings.join("；")}</Alert> : null}
              </Stack>
            ) : <Typography variant="body2" color="text.secondary">还没有执行过索引同步。</Typography>}
          </Stack>
        </CardContent>
      </Card>

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
            <DialogContentText id="rag-full-rebuild-description">将重新分块并嵌入全部资料，耗时可能较长。新索引通过校验前，当前已发布索引会继续提供查询服务。</DialogContentText>
            <Alert severity="warning">仅在首次初始化、索引需要修复、模型或分块规则变化时使用。普通资料更新请选择“增量同步”。</Alert>
            {pendingFullPlan?.summary ? <Typography variant="body2" color="text.secondary">预检：扫描 {pendingFullPlan.summary.scanned_sources ?? 0} 个来源 · 预计嵌入 {pendingFullPlan.summary.embedded_documents ?? 0} 个文档</Typography> : null}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2, gap: 1, flexWrap: "wrap" }}>
          <Button autoFocus disabled={startingMode === "full"} onClick={() => { setFullConfirmOpen(false); setPendingFullPlan(null); }} sx={{ minHeight: 44 }}>取消</Button>
          <Button color="warning" variant="contained" disabled={startingMode === "full"} onClick={() => void handleConfirmFullSync()} startIcon={startingMode === "full" ? <CircularProgress size={16} color="inherit" /> : undefined} sx={{ minHeight: 44 }}>确认全量重建</Button>
        </DialogActions>
      </Dialog>
    </SettingsShell>
  );
}
