"use client";

import ArrowForwardRoundedIcon from "@mui/icons-material/ArrowForwardRounded";
import CheckCircleOutlineRoundedIcon from "@mui/icons-material/CheckCircleOutlineRounded";
import ErrorOutlineRoundedIcon from "@mui/icons-material/ErrorOutlineRounded";
import StorageOutlinedIcon from "@mui/icons-material/StorageOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import WarningAmberRoundedIcon from "@mui/icons-material/WarningAmberRounded";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, Stack, Typography } from "@mui/material";
import { getModelCatalog, getRagSettings, normalizeModelOptions } from "@/lib/api";
import { isGatewayBackedModel } from "@/lib/model-options.mjs";
import { settingsModelsHref, settingsRagHref } from "@/lib/task-routes";
import { ModelOption, RagSettingsStatus } from "@/lib/types";
import { SettingsShell } from "./settings-shell";

function isTerminalSync(status?: string) {
  return status === "succeeded" || status === "failed" || status === "interrupted";
}

export default function SettingsOverviewClient() {
  const [ragStatus, setRagStatus] = useState<RagSettingsStatus | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [ragError, setRagError] = useState("");
  const [modelsError, setModelsError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    const [ragResult, modelsResult] = await Promise.allSettled([
      getRagSettings(),
      getModelCatalog(),
    ]);

    if (ragResult.status === "fulfilled") {
      setRagStatus(ragResult.value);
      setRagError("");
    } else {
      setRagError(ragResult.reason instanceof Error ? ragResult.reason.message : "读取 RAG 状态失败");
    }

    if (modelsResult.status === "fulfilled") {
      setModels(normalizeModelOptions(modelsResult.value.data ?? []).filter((model) => isGatewayBackedModel(model)));
      setModelsError("");
    } else {
      setModelsError(modelsResult.reason instanceof Error ? modelsResult.reason.message : "读取模型目录失败");
    }
    setLoading(false);
  };

  useEffect(() => {
    void load();
  }, []);

  const activeJob = ragStatus?.active_sync_job;
  const syncLabel = activeJob && !isTerminalSync(activeJob.status)
    ? activeJob.phase_label ?? "正在后台同步"
    : ragStatus?.available
      ? "索引可用"
      : "尚未构建";
  const canIncremental = ragStatus?.sync_capability?.incremental_ready !== false;

  return (
    <SettingsShell section="overview">
      {ragError || modelsError ? (
        <Alert
          severity="warning"
          role="alert"
          action={<Button color="inherit" size="small" onClick={() => void load()}>重试</Button>}
        >
          {ragError || modelsError}；其余设置仍可进入。
        </Alert>
      ) : null}

      <Stack spacing={1}>
        <Typography variant="overline" color="text.secondary">配置总览</Typography>
        <Typography variant="body2" color="text.secondary">
          日常只需查看这里；涉及索引或协议时，再进入对应页面操作。
        </Typography>
      </Stack>

      <Card variant="outlined" className="card-lift" sx={{ boxShadow: "none" }}>
        <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
              <Stack direction="row" spacing={1.25} alignItems="flex-start" sx={{ minWidth: 0 }}>
                <StorageOutlinedIcon color="primary" aria-hidden="true" sx={{ mt: 0.25 }} />
                <Stack spacing={0.5} sx={{ minWidth: 0 }}>
                  <Typography variant="h6">小说 RAG 数据库</Typography>
                  <Typography variant="body2" color="text.secondary">
                    管理示例小说与归档正文的检索索引；同步任务可在后台持续执行。
                  </Typography>
                </Stack>
              </Stack>
              {loading ? <CircularProgress size={20} aria-label="正在读取 RAG 状态" /> : (
                <Chip
                  size="small"
                  color={ragStatus?.available ? "success" : activeJob ? "info" : "default"}
                  icon={ragStatus?.available ? <CheckCircleOutlineRoundedIcon /> : <ErrorOutlineRoundedIcon />}
                  label={syncLabel}
                  sx={{ flexShrink: 0 }}
                />
              )}
            </Stack>

            <Divider />

            <Stack direction={{ xs: "column", sm: "row" }} spacing={{ xs: 0.75, sm: 2 }} useFlexGap>
              <Typography variant="body2" color="text.secondary">
                {ragStatus?.sources?.length ? `已配置 ${ragStatus.sources.length} 类语料来源` : "暂未读取到语料来源"}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {canIncremental ? "日常更新可使用增量同步" : "当前索引需先执行全量重建"}
              </Typography>
            </Stack>

            <Box>
              <Button component={Link} href={settingsRagHref()} variant="contained" endIcon={<ArrowForwardRoundedIcon />} sx={{ minHeight: 44 }}>
                管理 RAG 同步
              </Button>
            </Box>
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined" className="card-lift" sx={{ boxShadow: "none" }}>
        <CardContent sx={{ p: { xs: 1.75, sm: 2.5 }, "&:last-child": { pb: { xs: 1.75, sm: 2.5 } } }}>
          <Stack spacing={2}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
              <Stack direction="row" spacing={1.25} alignItems="flex-start" sx={{ minWidth: 0 }}>
                <TuneOutlinedIcon color="primary" aria-hidden="true" sx={{ mt: 0.25 }} />
                <Stack spacing={0.5} sx={{ minWidth: 0 }}>
                  <Typography variant="h6">模型协议</Typography>
                  <Typography variant="body2" color="text.secondary">
                    为 Gateway 模型指定 OpenAI 或 Anthropic 协议，协议变更会影响后续请求。
                  </Typography>
                </Stack>
              </Stack>
              {loading ? <CircularProgress size={20} aria-label="正在读取模型目录" /> : (
                <Chip size="small" color={models.length ? "primary" : "default"} label={models.length ? `${models.length} 个可配置模型` : "暂无可配置模型"} sx={{ flexShrink: 0 }} />
              )}
            </Stack>

            <Divider />

            <Box>
              <Button component={Link} href={settingsModelsHref()} variant="outlined" endIcon={<ArrowForwardRoundedIcon />} sx={{ minHeight: 44 }}>
                管理模型协议
              </Button>
            </Box>
          </Stack>
        </CardContent>
      </Card>

      <Alert severity="warning" icon={<WarningAmberRoundedIcon />}>
        全量重建会重新处理全部资料，且需二次确认；普通资料更新请在 RAG 页面使用增量同步。模型协议仅在确认网关兼容性后再修改。
      </Alert>
    </SettingsShell>
  );
}
