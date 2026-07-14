"use client";

import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  LinearProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import {
  Cancel as CancelIcon,
  CheckCircle as CheckCircleIcon,
  Delete as DeleteIcon,
  Error as ErrorIcon,
  HourglassEmpty as RunningIcon,
  PlayArrow as PlayIcon,
  RadioButtonUnchecked as PendingIcon,
} from "@mui/icons-material";
import type { ModelOption } from "@/lib/types";
import { CHECK_STATUS_LABELS, VALIDATION_STATUS_LABELS } from "./model-validation-state.mjs";

const validationStatusLabels = VALIDATION_STATUS_LABELS as Record<string, string>;
const checkStatusLabels = CHECK_STATUS_LABELS as Record<string, string>;

interface ValidationCheckView {
  id: string;
  label?: string;
  status: string;
  summary?: string;
  failure_reason?: string;
}

interface ValidationStateView {
  status: string;
  checks: ValidationCheckView[];
  report: unknown | null;
  failureReason?: string;
  reasoningSignal?: boolean;
  reasoningChars?: number;
}

interface ModelValidationPanelProps {
  model: ModelOption | null;
  state: ValidationStateView;
  running: boolean;
  onRun: () => void;
  onClear: () => void;
  onCancel: () => void;
}

function statusColor(status: string) {
  if (status === "verified") return "success";
  if (status === "failed") return "error";
  if (status === "running") return "info";
  if (status === "cancelled") return "warning";
  return "default";
}

function checkIcon(check: ValidationCheckView) {
  if (check.status === "passed") return <CheckCircleIcon color="success" fontSize="small" />;
  if (check.status === "failed") return <ErrorIcon color="error" fontSize="small" />;
  if (check.status === "running") return <RunningIcon color="info" fontSize="small" />;
  if (check.status === "skipped") return <CancelIcon color="disabled" fontSize="small" />;
  return <PendingIcon color="disabled" fontSize="small" />;
}

export default function ModelValidationPanel({
  model,
  state,
  running,
  onRun,
  onClear,
  onCancel,
}: ModelValidationPanelProps) {
  const statusLabel = validationStatusLabels[state.status] || state.status;
  const failureReason = state.failureReason || (model?.metadata?.validation?.failure_reason ?? model?.metadata?.validation?.last_error);
  const hasReport = Boolean(state.report || model?.metadata?.validation);
  const canClear = hasReport && !running;

  return (
    <Card variant="outlined" sx={{ height: "100%", borderRadius: 2, overflow: "hidden" }}>
      <CardContent sx={{ p: 2, height: "100%", display: "flex", flexDirection: "column", gap: 1.5 }}>
        <Stack spacing={0.75}>
          <Typography variant="overline" color="text.secondary">
            模型验证
          </Typography>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, wordBreak: "break-word" }}>
            {model?.display_name || model?.id || "未选择模型"}
          </Typography>
          {model?.provider ? (
            <Typography variant="caption" color="text.secondary">
              {model.provider}
            </Typography>
          ) : null}
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Chip size="small" color={statusColor(state.status)} label={statusLabel} />
            {model?.metadata?.compatibility ? (
              <Chip size="small" variant="outlined" label={`目录：${model.metadata.compatibility}`} />
            ) : null}
          </Stack>
        </Stack>

        {running ? <LinearProgress role="status" aria-label="模型验证进行中" /> : null}

        {state.status === "verified" ? (
          <Alert severity="success" sx={{ py: 0.5 }}>
            该模型已可用于小说任务流。
          </Alert>
        ) : null}
        {failureReason ? (
          <Alert severity={state.status === "cancelled" ? "warning" : "error"} sx={{ py: 0.5 }}>
            {failureReason}
          </Alert>
        ) : null}
        {state.reasoningSignal ? (
          <Alert severity="info" sx={{ py: 0.5 }}>
            推理信号元数据：累计 {state.reasoningChars ?? 0} 字符。
          </Alert>
        ) : null}

        <Stack direction="row" spacing={1} flexWrap="wrap">
          <Button
            size="small"
            variant="contained"
            startIcon={<PlayIcon />}
            disabled={!model || running}
            onClick={onRun}
          >
            {hasReport ? "重新验证" : "运行验证"}
          </Button>
          <Button size="small" variant="outlined" disabled={!running} onClick={onCancel}>
            取消
          </Button>
          <Button
            size="small"
            variant="outlined"
            color="error"
            startIcon={<DeleteIcon />}
            disabled={!canClear}
            onClick={onClear}
          >
            清除
          </Button>
        </Stack>

        <Divider />

        <Box sx={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
          <List dense disablePadding>
            {state.checks.map((check) => (
              <ListItem key={check.id} disableGutters alignItems="flex-start" sx={{ py: 0.75 }}>
                <ListItemIcon sx={{ minWidth: 32, pt: 0.25 }}>{checkIcon(check)}</ListItemIcon>
                <ListItemText
                  primary={
                    <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {check.label || check.id}
                      </Typography>
                      <Chip
                        size="small"
                        variant="outlined"
                        label={checkStatusLabels[check.status] || check.status}
                        sx={{ height: 22 }}
                      />
                    </Stack>
                  }
                  secondary={
                    <Box component="span">
                      {check.summary ? (
                        <Typography component="span" variant="caption" color="text.secondary" sx={{ display: "block" }}>
                          {check.summary}
                        </Typography>
                      ) : null}
                      {check.failure_reason ? (
                        <Typography component="span" variant="caption" color="error.main" sx={{ display: "block" }}>
                          {check.failure_reason}
                        </Typography>
                      ) : null}
                    </Box>
                  }
                />
              </ListItem>
            ))}
          </List>
        </Box>
      </CardContent>
    </Card>
  );
}
