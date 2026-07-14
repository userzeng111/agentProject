"use client";

import { ReactNode, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Collapse,
  Stack,
  Typography,
} from "@mui/material";
import {
  CheckCircle as ConnectedIcon,
  LinkOff as DisconnectedIcon,
  Cached as ReconnectingIcon,
  Error as ErrorIcon,
} from "@mui/icons-material";

/**
 * 连接状态指示器
 */
function ConnectionBadge({ status }: { status: "connected" | "disconnected" | "reconnecting" | "error" }) {
  const config = {
    connected: { icon: <ConnectedIcon fontSize="inherit" />, label: "已连接", color: "success" as const },
    disconnected: { icon: <DisconnectedIcon fontSize="inherit" />, label: "未连接", color: "default" as const },
    reconnecting: { icon: <ReconnectingIcon fontSize="inherit" />, label: "重连中", color: "warning" as const },
    error: { icon: <ErrorIcon fontSize="inherit" />, label: "连接异常", color: "error" as const },
  };
  const { icon, label, color } = config[status];
  return <Chip icon={icon} label={label} size="small" color={color} variant="outlined" />;
}

/**
 * 日志条目渲染
 */
function EventItem({ event }: { event: { time: string; type: string; message: string; detail?: string } }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Box
      sx={{
        py: 0.75,
        px: 1.5,
        borderBottom: "1px solid",
        borderColor: "divider",
        "&:last-child": { borderBottom: "none" },
      }}
    >
      <Stack
        direction="row"
        spacing={1}
        alignItems="flex-start"
        role={event.detail ? "button" : undefined}
        tabIndex={event.detail ? 0 : undefined}
        aria-expanded={event.detail ? expanded : undefined}
        aria-controls={event.detail ? `event-detail-${event.time}` : undefined}
        sx={{ cursor: event.detail ? "pointer" : "default" }}
        onClick={() => event.detail && setExpanded((p) => !p)}
        onKeyDown={event.detail ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded((p) => !p); } } : undefined}
      >
        <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0, fontFamily: "monospace", fontSize: "0.72rem" }}>
          {event.time}
        </Typography>
        <Chip label={event.type} size="small" variant="outlined" sx={{ height: 20, fontSize: "0.65rem", flexShrink: 0 }} />
        <Typography variant="body2" sx={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>
          {event.message}
        </Typography>
      </Stack>
      {event.detail && (
        <Collapse in={expanded}>
          <Typography id={`event-detail-${event.time}`} variant="caption" color="text.secondary" sx={{ display: "block", pl: 3, pt: 0.5, fontFamily: "monospace", fontSize: "0.75rem", whiteSpace: "pre-wrap" }}>
            {event.detail}
          </Typography>
        </Collapse>
      )}
    </Box>
  );
}

export interface LiveEventLogProps {
  /** 连接状态 */
  connectionStatus: "connected" | "disconnected" | "reconnecting" | "error";
  /** 日志条目 */
  events: Array<{ time: string; type: string; message: string; detail?: string }>;
  /** 事件类型过滤白名单 */
  filterTypes?: string[];
  /** 加载中 */
  loading?: boolean;
  /** 错误信息 */
  error?: string;
  /** 空态文案 */
  emptyText?: string;
  /** 重试回调 */
  onRetry?: () => void;
  /** 附加头部内容 */
  headerContent?: ReactNode;
}

/**
 * 实时事件日志组件
 *
 * 渲染连接状态、事件列表、过滤和空/错误态。
 * 不管理任务状态机和 SSE，由父组件传入数据。
 */
export default function LiveEventLog({
  connectionStatus,
  events,
  filterTypes,
  loading = false,
  error: fetchError,
  emptyText = "暂无事件记录",
  onRetry,
  headerContent,
}: LiveEventLogProps) {
  const filtered = filterTypes?.length ? events.filter((e) => filterTypes.includes(e.type)) : events;

  return (
    <Box
      data-testid="live-event-log"
      sx={{
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 2,
        overflow: "hidden",
        bgcolor: "background.paper",
      }}
    >
      {/* 头部：连接状态指示 + 额外内容 */}
      <Stack
        direction="row"
        spacing={1}
        alignItems="center"
        sx={{ px: 1.5, py: 1, borderBottom: "1px solid", borderColor: "divider" }}
      >
        <ConnectionBadge status={connectionStatus} />
        {headerContent}
        {filterTypes?.length ? (
          <Chip label={`过滤: ${filterTypes.length} 类型`} size="small" variant="outlined" sx={{ ml: "auto" }} />
        ) : null}
      </Stack>

      {/* 错误态 */}
      {fetchError ? (
        <Alert severity="error" role="alert" action={onRetry ? <Chip label="重试" size="small" clickable onClick={onRetry} /> : undefined}>
          {fetchError}
        </Alert>
      ) : null}

      {/* 加载态 */}
      {loading ? (
        <Box sx={{ p: 3, textAlign: "center" }} role="status" aria-live="polite">
          <CircularProgress size={24} />
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            加载事件日志...
          </Typography>
        </Box>
      ) : null}

      {/* 日志列表 */}
      {!loading && !fetchError ? (
        filtered.length ? (
          <Box sx={{ maxHeight: 480, overflowY: "auto" }}>
            {filtered.map((event, i) => (
              <EventItem key={`${event.time}-${event.type}-${i}`} event={event} />
            ))}
          </Box>
        ) : (
          <Box sx={{ p: 3, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">{emptyText}</Typography>
          </Box>
        )
      ) : null}
    </Box>
  );
}

export { ConnectionBadge, EventItem };
