"use client";

import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Select,
  Stack,
  Typography,
} from "@mui/material";

import { ModelOption, RecoveryContractFields, RecoveryMode, RecoveryPreview } from "@/lib/types";
import { filterRecoveryModels, resolveRecoveryPreview } from "./recovery-state.mjs";

const ACTION_ORDER: RecoveryMode[] = ["recover_to_stable", "restart_from_input"];

const ACTION_LABELS: Record<RecoveryMode, string> = {
  recover_to_stable: "回填最近稳定阶段",
  restart_from_input: "按原始输入重新开始",
};

function getRecoveryOptions(recovery?: RecoveryContractFields | null) {
  return Array.isArray(recovery?.recovery_options) ? recovery.recovery_options : [];
}

function formatFallbackActions(actions?: RecoveryMode[]) {
  if (!Array.isArray(actions) || actions.length === 0) {
    return "";
  }
  return actions.map((action) => ACTION_LABELS[action] || action).join("、");
}

function formatTargetChapters(preview?: RecoveryPreview | null) {
  const chapterNumbers = Array.isArray(preview?.target_chapter_numbers)
    ? preview.target_chapter_numbers.filter((item) => Number.isInteger(item))
    : [];
  if (chapterNumbers.length === 1) {
    return `第 ${chapterNumbers[0]} 章`;
  }
  if (chapterNumbers.length > 1) {
    return `第 ${chapterNumbers[0]}-${chapterNumbers[chapterNumbers.length - 1]} 章`;
  }
  if (typeof preview?.target_chapter_number === "number" && Number.isInteger(preview.target_chapter_number)) {
    return `第 ${preview.target_chapter_number} 章`;
  }
  return "";
}

export interface RecoveryDialogProps {
  open: boolean;
  recovery?: RecoveryContractFields | null;
  models: ModelOption[];
  selectedAction: RecoveryMode;
  selectedModelId: string;
  defaultModelId?: string;
  submitting?: boolean;
  onActionChange: (action: RecoveryMode) => void;
  onModelChange: (modelId: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function RecoveryDialog({
  open,
  recovery,
  models,
  selectedAction,
  selectedModelId,
  defaultModelId = "",
  submitting = false,
  onActionChange,
  onModelChange,
  onCancel,
  onConfirm,
}: RecoveryDialogProps) {
  const options = getRecoveryOptions(recovery);
  const selectedOption = options.find((option) => option.action === selectedAction) ?? null;
  const preview = resolveRecoveryPreview(recovery, selectedAction);
  const filteredModels = filterRecoveryModels(models, preview?.allowed_model_ids);
  const taskDefaultModelAvailable = Boolean(
    defaultModelId && filteredModels.some((model) => model.id === defaultModelId),
  );
  const selectedModelAvailable = Boolean(
    selectedModelId && filteredModels.some((model) => model.id === selectedModelId),
  );
  const canConfirm = Boolean(selectedOption?.available && selectedModelAvailable);
  const stableOption = options.find((option) => option.action === "recover_to_stable") ?? null;
  const noStableTarget = stableOption && !stableOption.available;
  const fallbackActions = formatFallbackActions(preview?.fallback_actions);
  const targetChapters = formatTargetChapters(preview);

  return (
    <Dialog
      open={open}
      onClose={submitting ? undefined : onCancel}
      fullWidth
      maxWidth="sm"
      disableEscapeKeyDown={submitting}
    >
      <DialogTitle>恢复方案确认</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2.5}>
          {noStableTarget ? (
            <Alert severity="info">当前没有可回填的稳定阶段，建议改为按原始输入重新开始。</Alert>
          ) : null}

          <FormControl component="fieldset">
            <FormLabel component="legend">恢复动作</FormLabel>
            <RadioGroup
              value={selectedAction}
              onChange={(event) => onActionChange(event.target.value as RecoveryMode)}
              sx={{ mt: 1 }}
            >
              {ACTION_ORDER.map((action) => {
                const option = options.find((item) => item.action === action) ?? null;
                const available = Boolean(option?.available);
                return (
                  <Box
                    key={action}
                    sx={{
                      px: 1.5,
                      py: 1,
                      borderRadius: 2,
                      border: "1px solid",
                      borderColor: selectedAction === action ? "primary.main" : "divider",
                      backgroundColor: selectedAction === action ? "rgba(39, 100, 81, 0.05)" : "transparent",
                      mb: 1,
                    }}
                  >
                    <FormControlLabel
                      value={action}
                      control={<Radio />}
                      disabled={!available}
                      label={option?.label || ACTION_LABELS[action]}
                      sx={{ alignItems: "flex-start", m: 0 }}
                    />
                    {!available && option?.reason_unavailable ? (
                      <Typography variant="caption" color="text.secondary" sx={{ pl: 4.5 }}>
                        {option.reason_unavailable}
                      </Typography>
                    ) : null}
                  </Box>
                );
              })}
            </RadioGroup>
          </FormControl>

          <Box
            sx={{
              p: 2,
              borderRadius: 2,
              border: "1px solid",
              borderColor: "divider",
              backgroundColor: "rgba(29, 42, 39, 0.03)",
            }}
          >
            <Stack spacing={1}>
              <Typography variant="subtitle1">当前动作预览</Typography>
              <Typography variant="body2">
                恢复目标：{preview?.target_stage_label || "当前动作暂未提供恢复目标"}
              </Typography>
              {targetChapters ? (
                <Typography variant="body2">
                  目标章节：{targetChapters}
                  {typeof preview?.target_batch_no === "number" ? ` · 批次 ${preview.target_batch_no}` : ""}
                </Typography>
              ) : null}
              {preview?.reuse_existing_draft ? (
                <Typography variant="body2">草稿策略：将优先复用该章节已有历史草稿。</Typography>
              ) : null}
              <Typography variant="body2">
                恢复后果：
                {preview
                  ? preview.will_resume_generation
                    ? "恢复后会继续进入生成链路。"
                    : "恢复后停留在该稳定阶段，等待你继续处理。"
                  : "当前动作暂未提供后果说明。"}
              </Typography>
              <Typography variant="body2">
                默认模型：{preview?.default_model_id || defaultModelId || "未设置"}
              </Typography>
              <Typography variant="body2">
                最近一次动作模型：{preview?.last_action_model_id || "未记录"}
              </Typography>
              {fallbackActions ? <Typography variant="body2">失败兜底：{fallbackActions}</Typography> : null}
            </Stack>
          </Box>

          <Box
            sx={{
              p: 2,
              borderRadius: 2,
              border: "1px solid",
              borderColor: "divider",
            }}
          >
            <Stack spacing={1.5}>
              <Typography variant="subtitle1">本次模型</Typography>
              {filteredModels.length > 0 ? (
                <Select
                  size="small"
                  displayEmpty
                  value={selectedModelAvailable ? selectedModelId : ""}
                  onChange={(event) => onModelChange(String(event.target.value))}
                  sx={{ maxWidth: 360 }}
                >
                  <MenuItem value="">
                    <em>请选择恢复模型</em>
                  </MenuItem>
                  {filteredModels.map((model) => (
                    <MenuItem key={model.id} value={model.id}>
                      {(model.display_name || model.id) + (model.provider ? ` · ${model.provider}` : "")}
                    </MenuItem>
                  ))}
                </Select>
              ) : (
                <Alert severity="warning">当前动作没有可用模型，请切换恢复动作或稍后再试。</Alert>
              )}

              {!taskDefaultModelAvailable && filteredModels.length > 0 ? (
                <Alert severity="warning">任务默认模型当前不可用，请手动选择恢复模型。</Alert>
              ) : null}

              <Typography variant="caption" color="text.secondary">
                默认优先采用任务默认模型；最近一次动作模型仅作为参考展示。
              </Typography>
            </Stack>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} disabled={submitting}>
          取消
        </Button>
        <Button variant="contained" onClick={onConfirm} disabled={!canConfirm || submitting}>
          {submitting ? "提交中..." : "确认执行当前动作"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
