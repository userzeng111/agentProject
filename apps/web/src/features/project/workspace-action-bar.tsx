"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Stack,
  Tooltip,
} from "@mui/material";
import {
  Cancel as CancelIcon,
  Delete as DeleteIcon,
} from "@mui/icons-material";
// ActionAvailability 类型定义自 project-action-availability.mjs
// 使用内联类型以兼容 .mjs 模块
interface ActionAvailability {
  available: boolean;
  reason: string | null;
  label: string;
  confirmPrompt?: string;
  targetView?: string;
  requestStatus: "idle" | "running" | "success" | "failed";
}

/**
 * 单一动作按钮组件
 *
 * 根据 ActionAvailability 渲染:
 * - available=true → 可点击的动作按钮
 * - available=false + reason → 带 Tooltip 的禁用按钮或状态文字
 * - requestStatus === "running" → 提交中状态
 */
function ActionButton({
  action,
  onClick,
  href,
  color = "primary",
  variant = "contained",
  icon,
}: {
  action: ActionAvailability;
  onClick?: () => void;
  href?: string;
  color?: "primary" | "warning" | "error" | "info" | "secondary" | "success";
  variant?: "contained" | "outlined" | "text";
  icon?: React.ReactNode;
}) {
  const isSubmitting = action.requestStatus === "running";

  if (!action.available && action.reason) {
    return (
      <Tooltip title={action.reason}>
        <span>
          <Button
            disabled
            size="small"
            variant={variant}
            color={color}
            startIcon={icon}
          >
            {action.label}
          </Button>
        </span>
      </Tooltip>
    );
  }

  if (!action.available) {
    return null;
  }

  if (href) {
    return (
      <Button
        component={Link}
        href={href}
        size="small"
        variant={variant}
        color={color}
        startIcon={icon}
      >
        {isSubmitting ? "提交中..." : action.label}
      </Button>
    );
  }

  return (
    <Button
      size="small"
      variant={variant}
      color={color}
      disabled={isSubmitting}
      onClick={onClick}
      startIcon={icon}
    >
      {isSubmitting ? "提交中..." : action.label}
    </Button>
  );
}

/**
 * 确认操作弹窗
 */
function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "确认",
  onConfirm,
  onCancel,
  loading,
}: {
  open: boolean;
  title: string;
  message?: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}) {
  return (
    <Dialog open={open} onClose={onCancel} aria-labelledby="confirm-dialog-title">
      <DialogTitle id="confirm-dialog-title">{title}</DialogTitle>
      {message && (
        <DialogContent>
          <DialogContentText>{message}</DialogContentText>
        </DialogContent>
      )}
      <DialogActions>
        <Button onClick={onCancel} disabled={loading}>取消</Button>
        <Button onClick={onConfirm} disabled={loading} variant="contained" autoFocus>
          {loading ? "提交中..." : confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/**
 * 项目主动作条
 *
 * 集中管理: 主动作、确认弹窗、禁用原因、提交中状态
 * 任何写操作使用本地 confirmState 防止重复提交
 */
export default function WorkspaceActionBar({
  actions,
  onRun,
  onContinue,
  onRecoverOpen,
  onCancel,
  onDelete,
  onArchive,
  onRefresh,
  reviewHref,
  resultHref,
  isSubmitting,
}: {
  actions: {
    runOrContinue: ActionAvailability;
    review: ActionAvailability;
    viewResult: ActionAvailability;
    archive: ActionAvailability;
    delete: ActionAvailability;
    cancel: ActionAvailability;
    recover: ActionAvailability;
  };
  onRun?: () => void;
  onContinue?: () => void;
  onRecoverOpen?: () => void;
  onCancel?: () => void;
  onDelete?: () => void;
  onArchive?: () => void;
  onRefresh?: () => void;
  reviewHref?: string;
  resultHref?: string;
  isSubmitting?: boolean;
}) {
  const [confirmState, setConfirmState] = useState<{
    type: "delete" | "cancel" | "archive";
    open: boolean;
  }>({ type: "delete", open: false });

  const requestInFlight = isSubmitting || actions.runOrContinue.requestStatus === "running";

  const handleOpenConfirm = useCallback((type: "delete" | "cancel" | "archive") => {
    setConfirmState({ type, open: true });
  }, []);

  const handleCloseConfirm = useCallback(() => {
    setConfirmState({ type: "delete", open: false });
  }, []);

  const handleConfirmAction = useCallback(() => {
    if (confirmState.type === "cancel" && onCancel) {
      onCancel();
    } else if (confirmState.type === "delete" && onDelete) {
      onDelete();
    } else if (confirmState.type === "archive" && onArchive) {
      onArchive();
    }
    setConfirmState({ type: confirmState.type, open: false });
  }, [confirmState.type, onArchive, onCancel, onDelete]);

  const confirmConfig = {
    delete: {
      title: "删除任务",
      message: actions.delete.confirmPrompt || "确认删除此任务？此操作不可恢复。",
      confirmLabel: "确认删除",
    },
    cancel: {
      title: "取消任务",
      message: actions.cancel.confirmPrompt || "确认取消此任务？",
      confirmLabel: "确认取消",
    },
    archive: {
      title: "归档任务",
      message: actions.archive.confirmPrompt || "确认将此任务归档？",
      confirmLabel: "确认归档",
    },
  };

  return (
    <>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        {/* 运行/继续创作 */}
        {actions.runOrContinue.available && onRun && (
          <ActionButton
            action={{ ...actions.runOrContinue, requestStatus: requestInFlight ? "running" : actions.runOrContinue.requestStatus }}
            onClick={onRun}
          />
        )}

        {/* 继续创作（ready_for_batch 单独 handler） */}
        {actions.runOrContinue.available && onContinue && (
          <ActionButton
            action={{ ...actions.runOrContinue, requestStatus: requestInFlight ? "running" : actions.runOrContinue.requestStatus }}
            onClick={onContinue}
          />
        )}

        {/* 进入审核 */}
        {actions.review.available && actions.review.targetView && reviewHref && (
          <ActionButton action={actions.review} href={reviewHref} />
        )}

        {/* 查看结果 */}
        {actions.viewResult.available && actions.viewResult.targetView && resultHref && (
          <ActionButton action={actions.viewResult} href={resultHref} color="success" />
        )}

        {/* 恢复 */}
        {actions.recover.available && onRecoverOpen && (
          <ActionButton
            action={actions.recover}
            onClick={onRecoverOpen}
            color="warning"
            variant="outlined"
          />
        )}

        {/* 取消 */}
        {actions.cancel.available && onCancel && (
          <ActionButton
            action={actions.cancel}
            onClick={() => handleOpenConfirm("cancel")}
            color="warning"
            variant="outlined"
            icon={<CancelIcon />}
          />
        )}

        {/* 删除 */}
        {actions.delete.available && onDelete && (
          <ActionButton
            action={actions.delete}
            onClick={() => handleOpenConfirm("delete")}
            color="error"
            variant="outlined"
            icon={<DeleteIcon />}
          />
        )}

        {/* 归档 */}
        {actions.archive.available && onArchive && (
          <ActionButton
            action={{ ...actions.archive, requestStatus: requestInFlight ? "running" : actions.archive.requestStatus }}
            onClick={() => handleOpenConfirm("archive")}
            color="info"
            variant="outlined"
          />
        )}

        {/* 刷新按钮始终存在 */}
        {onRefresh && (
          <Button variant="text" size="small" onClick={onRefresh} disabled={requestInFlight}>
            刷新
          </Button>
        )}
      </Stack>

      <ConfirmDialog
        open={confirmState.open}
        title={confirmConfig[confirmState.type].title}
        message={confirmConfig[confirmState.type].message}
        confirmLabel={confirmConfig[confirmState.type].confirmLabel}
        onConfirm={handleConfirmAction}
        onCancel={handleCloseConfirm}
        loading={requestInFlight}
      />
    </>
  );
}

export { ActionButton, ConfirmDialog };
