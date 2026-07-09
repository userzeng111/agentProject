"use client";

import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { buildAgentDebugDiagnostics } from "@/features/task-run/debug-diagnostics.mjs";
import type { WorkspaceEvent, WorkspaceResponse } from "@/lib/types";

type Tone = "default" | "success" | "warning" | "error";

interface StatusBlock {
  status?: string;
  title?: string;
  summary?: string;
  tone?: Tone;
}

interface DebugPanelProps {
  workspace: WorkspaceResponse;
  streamState: string;
  streamPath?: string;
  streamPaths?: string[];
  onRefresh: () => void;
  onOpenRecovery: () => void;
}

function toneToChipColor(tone?: string): "default" | "success" | "warning" | "error" {
  if (tone === "success" || tone === "warning" || tone === "error") {
    return tone;
  }
  return "default";
}

function statusToChipColor(status?: string): "default" | "success" | "warning" | "error" | "info" {
  if (status === "ok" || status === "available" || status === "connected" || status === "injected" || status === "ready") {
    return "success";
  }
  if (status === "warning" || status === "unknown" || status === "reconnecting" || status === "not_ready") {
    return "warning";
  }
  if (status === "error" || status === "failed") {
    return "error";
  }
  return "default";
}

function formatNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "未上报";
}

function formatDuration(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? `${Math.round(value)} ms` : "未上报";
}

function formatPercent(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "未上报";
}

function formatTime(value?: string) {
  if (!value) return "未上报";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString();
}

function formatEvidence(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "无";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.length ? value.map(formatEvidence).join("；") : "空数组";
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, entryValue]) => {
      if (entryValue === null || entryValue === undefined || entryValue === "") return false;
      if (typeof entryValue === "number") return Number.isFinite(entryValue);
      if (Array.isArray(entryValue)) return entryValue.length > 0;
      if (typeof entryValue === "object") return Object.keys(entryValue as Record<string, unknown>).length > 0;
      return true;
    });
    return entries.length
      ? entries.map(([key, entryValue]) => `${key}: ${formatEvidence(entryValue)}`).join("；")
      : "无";
  }
  return String(value);
}

function hasRecoveryEntry(workspace: WorkspaceResponse) {
  return Boolean(
    workspace.recommended_action === "recover_to_stable" ||
      workspace.recommended_action === "restart_from_input" ||
      workspace.recovery_options?.some((option) => option.available),
  );
}

function sectionTitle(title: string, status?: string, color: ReturnType<typeof statusToChipColor> = "default") {
  return (
    <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
      <Typography variant="h6">{title}</Typography>
      {status ? <Chip size="small" label={status} color={color} variant={color === "default" ? "outlined" : "filled"} /> : null}
    </Stack>
  );
}

function DiagnosticBlock({ block }: { block: StatusBlock }) {
  return (
    <Stack spacing={0.75}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="subtitle1">{block.title || "未命名状态"}</Typography>
        <Chip
          size="small"
          label={block.status || "unknown"}
          color={toneToChipColor(block.tone)}
          variant={block.tone ? "filled" : "outlined"}
        />
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {block.summary || "暂无摘要。"}
      </Typography>
    </Stack>
  );
}

function MetricChips({ items }: { items: Array<{ label: string; value: unknown }> }) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {items.map((item) => (
        <Chip key={item.label} size="small" variant="outlined" label={`${item.label}：${item.value}`} />
      ))}
    </Stack>
  );
}

function renderEventSecondary(event: WorkspaceEvent) {
  return [
    `${event.stage || "未知阶段"} · ${event.event_type || "未知事件"} · ${formatTime(event.created_at)}`,
    event.md_ref ? `Markdown：${event.md_ref}` : "",
    event.json_ref ? `JSON：${event.json_ref}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

export default function DebugPanel({
  workspace,
  streamState,
  streamPath,
  streamPaths,
  onRefresh,
  onOpenRecovery,
}: DebugPanelProps) {
  const diagnostics = buildAgentDebugDiagnostics(workspace, { streamState });
  const health = diagnostics.health as StatusBlock;
  const connection = diagnostics.connection as StatusBlock & { raw?: string };
  const stateCheck = diagnostics.stateCheck;
  const context = diagnostics.context;
  const llm = diagnostics.llm;
  const llmUsageMissing = typeof llm.usageMissingCount === "number" && llm.usageMissingCount > 0;
  const formatLlmToken = (value: unknown) => (llm.usageStatus === "missing" && llmUsageMissing ? "未上报" : formatNumber(value));
  const jsonParseFailureBreakdown = (llm.jsonParseFailureBreakdown || {}) as Record<string, unknown>;
  const agentTrace = diagnostics.agentTrace;
  const rag = diagnostics.rag as StatusBlock & { source?: string; lastQueryStage?: string; injectionEvidence?: string };
  const evidenceLinks = Array.isArray(diagnostics.evidenceLinks) ? diagnostics.evidenceLinks : [];
  const recentEvents = [...(workspace.recent_events || [])].slice(-8).reverse();
  const candidatePaths = streamPaths?.length ? streamPaths : streamPath ? [streamPath] : [];
  const recoveryAvailable = hasRecoveryEntry(workspace);

  return (
    <Stack spacing={2.5}>
      <Box>
        {sectionTitle("诊断结论", health.status, toneToChipColor(health.tone))}
        <Box sx={{ mt: 1.5 }}>
          <Alert severity={health.tone === "default" ? "info" : health.tone || "info"}>
            <Stack spacing={1}>
              <DiagnosticBlock block={health} />
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Button size="small" variant="outlined" onClick={onRefresh}>
                  刷新工作区
                </Button>
                <Button size="small" variant="outlined" disabled={!recoveryAvailable} onClick={onOpenRecovery}>
                  打开恢复面板
                </Button>
              </Stack>
            </Stack>
          </Alert>
        </Box>
      </Box>

      <Divider />

      <Box>
        {sectionTitle("实时连接", connection.status, toneToChipColor(connection.tone))}
        <Stack spacing={1.25} sx={{ mt: 1.5 }}>
          <DiagnosticBlock block={connection} />
          <MetricChips
            items={[
              { label: "当前状态", value: streamState || "未上报" },
              { label: "当前路径", value: streamPath || candidatePaths[0] || "未上报" },
              { label: "候选路径", value: candidatePaths.length || "未上报" },
            ]}
          />
          {candidatePaths.length > 1 ? (
            <Typography variant="caption" color="text.secondary" sx={{ wordBreak: "break-all" }}>
              候选：{candidatePaths.join(" · ")}
            </Typography>
          ) : null}
        </Stack>
      </Box>

      <Divider />

      <Box>
        {sectionTitle("LLM 摘要", llm.status, statusToChipColor(llm.status))}
        <Stack spacing={1.25} sx={{ mt: 1.5 }}>
          <MetricChips
            items={[
              { label: "请求", value: formatNumber(llm.requestCount) },
              { label: "交换", value: formatNumber(llm.exchangeCount) },
              { label: "响应缓存命中", value: formatNumber(llm.runtimeResponseCacheHitCount ?? llm.cacheHitCount) },
              { label: "供应商缓存命中", value: formatNumber(llm.providerPromptCacheHitCount) },
              { label: "用量上报缺失", value: formatNumber(llm.usageMissingCount) },
              { label: "用量状态", value: llm.usageStatus || "未上报" },
              { label: "重试", value: formatNumber(llm.retryCount) },
              { label: "修复", value: formatNumber(llm.repairCount) },
              { label: "JSON 解析失败", value: formatNumber(llm.jsonParseFailedCount) },
            ]}
          />
          <MetricChips
            items={[
              { label: "供应商拒答", value: formatNumber(jsonParseFailureBreakdown.providerRefusalCount ?? 0) },
              { label: "空截断", value: formatNumber(jsonParseFailureBreakdown.emptyTruncatedCount ?? 0) },
              { label: "截断 JSON", value: formatNumber(jsonParseFailureBreakdown.truncatedJsonCount ?? 0) },
              {
                label: "普通 JSON 失败",
                value: formatNumber(jsonParseFailureBreakdown.ordinaryJsonParseFailedCount ?? 0),
              },
            ]}
          />
          <MetricChips
            items={[
              { label: "输入 tokens", value: formatLlmToken(llm.tokens?.inputTokens) },
              { label: "输出 tokens", value: formatLlmToken(llm.tokens?.outputTokens) },
              { label: "总 tokens", value: formatLlmToken(llm.tokens?.totalTokens) },
              { label: "缓存命中 tokens", value: formatLlmToken(llm.tokens?.cachedTokens) },
              { label: "缓存读取 tokens", value: formatLlmToken(llm.tokens?.cacheReadInputTokens) },
              { label: "缓存创建 tokens", value: formatLlmToken(llm.tokens?.cacheCreationInputTokens) },
              { label: "推理 tokens", value: formatLlmToken(llm.tokens?.reasoningTokens) },
            ]}
          />
          {llmUsageMissing ? (
            <Alert severity="warning">
              有 {formatNumber(llm.usageMissingCount)} 次模型请求没有上报 token 用量；历史任务无法从本地消息记录反推真实接口 token。
            </Alert>
          ) : null}
          <Typography variant="body2" color="text.secondary">
            最新模型：{llm.latestModel || "未上报"}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            最慢步骤：
            {llm.slowestStep?.exchangeLabel || llm.slowestStep?.stage || "未上报"}
            {" · "}
            {formatDuration(llm.slowestStep?.durationMs)}
            {llm.slowestStep?.model ? ` · ${llm.slowestStep.model}` : ""}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            首 Token 最慢：
            {llm.slowestFirstToken?.exchangeLabel || llm.slowestFirstToken?.stage || "未上报"}
            {" · "}
            {formatDuration(llm.slowestFirstToken?.firstTokenMs)}
          </Typography>
        </Stack>
      </Box>

      <Divider />

      <Box>
        {sectionTitle("Agent Trace", agentTrace.status, statusToChipColor(agentTrace.status))}
        <Stack spacing={1.25} sx={{ mt: 1.5 }}>
          <MetricChips
            items={[
              { label: "轮次", value: agentTrace.round || "未上报" },
              { label: "审核类型", value: agentTrace.reviewType || "未上报" },
              { label: "结论", value: agentTrace.verdict || "未上报" },
              { label: "评分", value: agentTrace.displayScore || "未上报" },
              { label: "完成 Agent", value: formatNumber(agentTrace.completedCount) },
              { label: "失败 Agent", value: formatNumber(agentTrace.failedCount) },
              { label: "运行记录", value: formatNumber(agentTrace.runCount) },
            ]}
          />
          <MetricChips
            items={[
              { label: "问题", value: formatNumber(agentTrace.issueCount) },
              { label: "警告", value: formatNumber(agentTrace.warningCount) },
            ]}
          />
          <Typography variant="body2" color="text.secondary">
            {agentTrace.comment || workspace.active_trace_summary || "暂无 Trace 摘要。"}
          </Typography>
        </Stack>
      </Box>

      <Divider />

      <Box>
        {sectionTitle("上下文/RAG", context.status, statusToChipColor(context.status))}
        <Stack spacing={1.25} sx={{ mt: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            {context.summary || "暂无上下文摘要。"}
          </Typography>
          <MetricChips
            items={[
              { label: "阶段", value: context.stage || "未上报" },
              { label: "阶段状态", value: context.stageStatus || "未上报" },
              { label: "当前 tokens", value: formatNumber(context.tokens?.currentTokens) },
              { label: "输入 tokens", value: formatNumber(context.tokens?.inputTokens) },
              { label: "输入上限", value: formatNumber(context.tokens?.maxInputTokens) },
              { label: "窗口占用", value: formatPercent(context.windowUsageRatio) },
            ]}
          />
          <MetricChips
            items={[
              { label: "压缩", value: context.compression?.applied ? "已启用" : "未启用" },
              { label: "压缩率", value: formatPercent(context.compression?.ratio) },
              { label: "上下文缓存", value: context.cache?.contextCacheHit ? "命中" : "未命中/未上报" },
              { label: "响应缓存", value: context.cache?.responseCacheHit ? "命中" : "未命中/未上报" },
              { label: "缓存片段", value: formatNumber(context.cache?.cachedSegments) },
            ]}
          />
          <DiagnosticBlock block={rag} />
          <MetricChips
            items={[
              { label: "RAG 来源", value: rag.source || "未上报" },
              { label: "最近查询阶段", value: rag.lastQueryStage || "未上报" },
              { label: "注入证据", value: rag.injectionEvidence || "未上报" },
            ]}
          />
          {context.items?.length ? (
            <List dense>
              {context.items.map((item: { label: string; status: string; summary: string; evidence: unknown }) => (
                <ListItem key={`${item.label}-${item.status}`} disableGutters alignItems="flex-start">
                  <ListItemText
                    primary={
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Typography variant="body2">{item.label}</Typography>
                        <Chip size="small" label={item.status} color={statusToChipColor(item.status)} variant="outlined" />
                      </Stack>
                    }
                    secondary={[item.summary, formatEvidence(item.evidence)].filter(Boolean).join("\n")}
                    secondaryTypographyProps={{ sx: { whiteSpace: "pre-line", wordBreak: "break-word" } }}
                  />
                </ListItem>
              ))}
            </List>
          ) : null}
        </Stack>
      </Box>

      <Divider />

      <Box>
        {sectionTitle("状态对账", stateCheck.status, statusToChipColor(stateCheck.status))}
        <Stack spacing={1.25} sx={{ mt: 1.5 }}>
          <Typography variant="body2" color="text.secondary">
            {stateCheck.summary || "暂无状态对账摘要。"}
          </Typography>
          <MetricChips
            items={[
              { label: "冲突", value: formatNumber(stateCheck.conflicts?.length) },
              { label: "提示", value: formatNumber(stateCheck.warnings?.length) },
              { label: "未知", value: formatNumber(stateCheck.unknowns?.length) },
              { label: "最近事件阶段", value: stateCheck.latestEventStage || "未上报" },
            ]}
          />
          <List dense>
            {stateCheck.items?.length ? (
              stateCheck.items.map((item: { code: string; label: string; status: string; summary: string; evidence: unknown }) => (
                <ListItem key={item.code || `${item.label}-${item.status}`} disableGutters alignItems="flex-start">
                  <ListItemText
                    primary={
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Typography variant="body2">{item.label}</Typography>
                        <Chip size="small" label={item.status} color={statusToChipColor(item.status)} />
                      </Stack>
                    }
                    secondary={[item.summary, `证据：${formatEvidence(item.evidence)}`].filter(Boolean).join("\n")}
                    secondaryTypographyProps={{ sx: { whiteSpace: "pre-line", wordBreak: "break-word" } }}
                  />
                </ListItem>
              ))
            ) : (
              <ListItem disableGutters>
                <ListItemText primary="暂无状态对账项目" />
              </ListItem>
            )}
          </List>
        </Stack>
      </Box>

      <Divider />

      <Box>
        {sectionTitle("最近事件与证据链接", undefined)}
        <Stack spacing={1.5} sx={{ mt: 1.5 }}>
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 0.5 }}>
              最近事件
            </Typography>
            <List dense>
              {recentEvents.length ? (
                recentEvents.map((event) => (
                  <ListItem key={event.event_id} disableGutters alignItems="flex-start">
                    <ListItemText
                      primary={event.message || event.event_type || "未命名事件"}
                      secondary={renderEventSecondary(event)}
                      secondaryTypographyProps={{ sx: { whiteSpace: "pre-line", wordBreak: "break-word" } }}
                    />
                  </ListItem>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="暂无最近事件" />
                </ListItem>
              )}
            </List>
          </Box>
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 0.5 }}>
              证据链接
            </Typography>
            <List dense>
              {evidenceLinks.length ? (
                evidenceLinks.slice(0, 12).map((link: Record<string, unknown>, index: number) => (
                  <ListItem key={`${String(link.path || link.label || "link")}-${index}`} disableGutters alignItems="flex-start">
                    <ListItemText
                      primary={
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Typography variant="body2">{String(link.label || "证据")}</Typography>
                          <Chip size="small" variant="outlined" label={String(link.category || "unknown")} />
                        </Stack>
                      }
                      secondary={[String(link.summary || ""), String(link.path || "")].filter(Boolean).join("\n")}
                      secondaryTypographyProps={{ sx: { whiteSpace: "pre-line", wordBreak: "break-word" } }}
                    />
                  </ListItem>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="暂无证据链接" />
                </ListItem>
              )}
            </List>
          </Box>
        </Stack>
      </Box>
    </Stack>
  );
}
