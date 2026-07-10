"use client";

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Chip,
  Collapse,
  Container,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  ExpandMore as ExpandMoreIcon,
  NavigateNext as NavigateNextIcon,
  CheckCircle as CheckCircleIcon,
  Edit as EditIcon,
  PlayArrow as PlayIcon,
  MenuBook as MenuBookIcon,
  Article as ArticleIcon,
  Verified as VerifiedIcon,
  AutoAwesome as AutoAwesomeIcon,
  Warning as WarningIcon,
  Error as ErrorIcon,
  Check as CheckIcon,
} from "@mui/icons-material";
import { fetchTextRef, getModelCatalog, getReview, normalizeModelOptions, recoverTask, resumeTask, rollbackChapterPlan } from "@/lib/api";
import RecoveryDialog from "@/features/task-recovery/recovery-dialog";
import { derivePrimaryRecoveryAction, filterRecoveryModels, resolveRecoveryPreview } from "@/features/task-recovery/recovery-state.mjs";
import { formatModelRefreshStatus, resolveSelectionAfterRefresh } from "@/features/task-models/model-refresh-state.mjs";
import { selectNovelTaskModels } from "@/lib/model-options.mjs";
import { resultHref, workspaceHref } from "@/lib/task-routes";
import { AgentTraceItem, ModelOption, ModelRefreshState, RecoveryMode, ReviewResponse, VerificationIssue } from "@/lib/types";
import MarkdownContent from "@/components/markdown-content";
import { ProjectShell } from "@/components/project-shell";
import { StageNav } from "@/components/stage-nav";
import { getCurrentTraceRound, inferExecutionKind, splitTraceRounds, summarizeTraceRound } from "./trace-rounds.mjs";
import { getValidationLinkFromError } from "@/features/chat/model-validation-state.mjs";
import { normalizeTaskActionErrorMessage } from "@/features/task-run/task-action-state.mjs";

const OUTLINE_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "大纲总纲", icon: <ArticleIcon fontSize="small" /> },
  { label: "审核", icon: <CheckCircleIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

const OUTLINE_BATCH_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "大纲总纲", icon: <ArticleIcon fontSize="small" /> },
  { label: "章节计划", icon: <ArticleIcon fontSize="small" /> },
  { label: "审核", icon: <CheckCircleIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

const CHAPTER_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "大纲", icon: <ArticleIcon fontSize="small" /> },
  { label: "正文", icon: <PlayIcon fontSize="small" /> },
  { label: "审核", icon: <CheckCircleIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

const VERIFY_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "大纲", icon: <ArticleIcon fontSize="small" /> },
  { label: "正文", icon: <PlayIcon fontSize="small" /> },
  { label: "验证", icon: <VerifiedIcon fontSize="small" /> },
  { label: "结果", icon: <MenuBookIcon fontSize="small" /> },
];

function ValidationErrorAlert({ message, modelId }: { message: string; modelId: string }) {
  const href = getValidationLinkFromError(message, modelId);
  return (
    <Alert
      severity="error"
      action={
        href ? (
          <Button component={Link} href={href} color="inherit" size="small">
            去 AI 对话验证
          </Button>
        ) : undefined
      }
    >
      {message}
    </Alert>
  );
}

function formatActionKindLabel(kind?: string) {
  const labels: Record<string, string> = {
    run: "启动执行",
    resume: "审核继续",
    continue: "继续创作",
    recover: "恢复重试",
  };
  return labels[kind || ""] || kind || "";
}

function resolveReviewTaskModelId(review?: ReviewResponse | null) {
  return review?.meta.creative_model_id || review?.meta.model_id || "";
}

function formatReviewModelLabel(review: ReviewResponse) {
  if (review.meta.auto_review_model_mode === "follow_creative") {
    const creativeModelId = resolveReviewTaskModelId(review);
    return `跟随任务创作模型${creativeModelId ? `（${creativeModelId}）` : ""}`;
  }
  return review.meta.review_model_id || "未设置";
}

function ReviewHistory({ history }: { history: ReviewResponse["review_history"] }) {
  if (!history?.length) return null;
  return (
    <Box>
      <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
        历史记录
      </Typography>
      <List dense>
        {history.map((item, index) => (
          <ListItem key={`${item.version}-${item.created_at ?? index}`} disableGutters>
            <ListItemText
              primary={`${item.version} · ${item.action}`}
              secondary={[item.comment, item.created_at ? new Date(item.created_at).toLocaleString() : ""]
                .filter(Boolean)
                .join(" · ")}
            />
          </ListItem>
        ))}
      </List>
    </Box>
  );
}

/** Agent 执行追踪面板 [NEW] */
function AgentTracePanel({ trace }: { trace: AgentTraceItem[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  if (!trace || trace.length === 0) {
    return (
      <Card sx={{ border: "1px solid", borderColor: "divider" }}>
        <CardContent>
          <Stack direction="row" spacing={1} alignItems="center">
            <AutoAwesomeIcon fontSize="small" color="disabled" />
            <Typography variant="subtitle1" fontWeight={600} color="text.secondary">
              Agent 审核追踪
            </Typography>
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            当前暂无 Agent 审核记录。若已开启自动审核，将在后台执行后显示；若未开启，可前往设置启用。
          </Typography>
        </CardContent>
      </Card>
    );
  }

  const traceRounds = splitTraceRounds(trace);
  const currentTraceRound = getCurrentTraceRound(trace);
  const historyRoundCount = Math.max(traceRounds.length - 1, 0);
  const {
    summaryEntry,
    agentItems,
    hasStructuredExecution,
    mainAgents,
    subAgents,
    synthesisAgents,
    trackedAgents,
    completedCount,
    failedCount,
    displayScore,
  } = summarizeTraceRound(currentTraceRound);
  const visibleAgents = showAll ? agentItems : agentItems.slice(0, 3);
  const hasMore = agentItems.length > 3;

  function getExecutionKindLabel(kind: "main_agent" | "subagent" | "synthesis") {
    if (kind === "main_agent") return "主 Agent";
    if (kind === "synthesis") return "综合裁决";
    return "子 Agent";
  }

  function getExecutionKindColor(kind: "main_agent" | "subagent" | "synthesis"): "primary" | "info" | "secondary" {
    if (kind === "main_agent") return "primary";
    if (kind === "synthesis") return "secondary";
    return "info";
  }

  function getInvocationLabel(invocationKind: string) {
    if (invocationKind === "function_call") return "函数调用";
    if (invocationKind === "orchestrate") return "编排调度";
    return invocationKind;
  }

  function getScoreColor(score: number | undefined) {
    if (score === undefined) return "default";
    if (score >= 80) return "success";
    if (score >= 60) return "warning";
    return "error";
  }

  function getStatusIcon(status: string) {
    if (status === "completed") return <CheckCircleIcon fontSize="small" color="success" />;
    if (status === "failed") return <ErrorIcon fontSize="small" color="error" />;
    if (status === "running") return <AutoAwesomeIcon fontSize="small" color="info" />;
    return <WarningIcon fontSize="small" color="disabled" />;
  }

  return (
    <Card sx={{ border: "1px solid", borderColor: "divider" }}>
      <CardContent sx={{ pb: 1 }}>
        {/* 头部 */}
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center">
            <AutoAwesomeIcon fontSize="small" color="primary" />
            <Typography variant="subtitle1" fontWeight={600}>
              Agent 审核追踪
            </Typography>
            {summaryEntry?.trace_round ? (
              <Chip
                label={`当前第 ${summaryEntry.trace_round} 轮`}
                size="small"
                variant="outlined"
              />
            ) : null}
            {hasStructuredExecution ? (
              <>
                <Chip
                  label={`${mainAgents.length} 个主 Agent`}
                  size="small"
                  color="primary"
                  variant="outlined"
                />
                <Chip
                  label={`${subAgents.length} 个子 Agent`}
                  size="small"
                  color="info"
                  variant="outlined"
                />
                {synthesisAgents.length > 0 && (
                  <Chip
                    label={`${synthesisAgents.length} 个综合裁决`}
                    size="small"
                    color="secondary"
                    variant="outlined"
                  />
                )}
              </>
            ) : (
              <Chip
                label={`${agentItems.length} 个 Agent`}
                size="small"
                color="primary"
                variant="outlined"
              />
            )}
            {failedCount > 0 && (
              <Chip label={`${failedCount} 个失败`} size="small" color="error" variant="outlined" />
            )}
            {historyRoundCount > 0 && (
              <Chip
                label={`历史 ${historyRoundCount} 轮`}
                size="small"
                variant="outlined"
              />
            )}
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <Chip
              label={`评分 ${displayScore} 分`}
              size="small"
              color={getScoreColor(displayScore)}
              variant="filled"
            />
            <Chip
              label={hasStructuredExecution ? `子执行 ${completedCount}/${trackedAgents.length} 完成` : `${completedCount}/${agentItems.length} 完成`}
              size="small"
              variant="outlined"
            />
            <Tooltip title={expanded ? "收起详情" : "展开详情"}>
              <IconButton
                size="small"
                onClick={() => setExpanded(expanded ? null : "all")}
              >
                <ExpandMoreIcon
                  sx={{
                    transform: expanded === "all" ? "rotate(180deg)" : "rotate(0deg)",
                    transition: "0.2s",
                  }}
                />
              </IconButton>
            </Tooltip>
          </Stack>
        </Stack>

        {historyRoundCount > 0 && (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
            当前仅统计最后一轮审核记录；历史轮次已保留但不再混入当前轮次计数。
          </Typography>
        )}

        {/* Agent 列表 */}
        {visibleAgents.map((agent: AgentTraceItem, index: number) => {
          const isExpanded = expanded === `agent-${index}`;
          const issues = agent.issues ?? [];
          const criticalIssues = issues.filter((i: VerificationIssue) => i.severity === "critical");
          const warningsFromIssues = issues.filter((i: VerificationIssue) => i.severity === "warning");
          const warningsFromField = agent.warnings ?? [];
          const warnings = warningsFromIssues.length > 0 ? warningsFromIssues : warningsFromField;
          const executionKind = inferExecutionKind(agent);

          return (
            <Box key={agent.agent_id || `${agent.role || "agent"}-${index}`} sx={{ mb: 1 }}>
              {/* Agent 行 */}
              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 1,
                  px: 1.5,
                  py: 1,
                  borderRadius: 1,
                  bgcolor: "background.default",
                  cursor: "pointer",
                  "&:hover": { bgcolor: "action.hover" },
                }}
                onClick={() => setExpanded(isExpanded ? null : `agent-${index}`)}
              >
                {getStatusIcon(agent.status || "pending")}
                <Typography variant="body2" fontWeight={500} sx={{ flex: 1 }}>
                  {agent.agent_name || agent.role || "未命名执行节点"}
                </Typography>
                {hasStructuredExecution && (
                  <Chip
                    label={getExecutionKindLabel(executionKind)}
                    size="small"
                    color={getExecutionKindColor(executionKind)}
                    variant="outlined"
                  />
                )}
                {agent.score !== undefined && agent.score !== null && (
                  <Chip
                    label={`${agent.score} 分`}
                    size="small"
                    color={getScoreColor(agent.score)}
                    sx={{ minWidth: 52 }}
                  />
                )}
                {criticalIssues.length > 0 && (
                  <Chip
                    label={`${criticalIssues.length} 严重`}
                    size="small"
                    color="error"
                    variant="outlined"
                  />
                )}
                {warnings.length > 0 && (
                  <Chip
                    label={`${warnings.length} 警告`}
                    size="small"
                    color="warning"
                    variant="outlined"
                  />
                )}
                <IconButton size="small">
                  <ExpandMoreIcon
                    sx={{
                      fontSize: 18,
                      transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                      transition: "0.2s",
                    }}
                  />
                </IconButton>
              </Box>

              {/* 展开详情 */}
              <Collapse in={isExpanded}>
                <Box sx={{ pl: 4, pr: 2, pb: 1.5, mt: 0.5 }}>
                  {/* 维度标签 */}
                  <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                    {hasStructuredExecution && (
                      <Chip label={getExecutionKindLabel(executionKind)} size="small" variant="outlined" />
                    )}
                    {agent.role && <Chip label={agent.role} size="small" variant="outlined" />}
                    {agent.status && <Chip label={agent.status} size="small" variant="outlined" />}
                    {agent.invocation_kind && (
                      <Chip label={getInvocationLabel(agent.invocation_kind)} size="small" variant="outlined" />
                    )}
                    {agent.duration_ms && (
                      <Chip label={`${Math.round(agent.duration_ms / 1000)}s`} size="small" variant="outlined" />
                    )}
                  </Stack>

                  {/* 推理过程 */}
                  {agent.reasoning && (
                    <Box sx={{ mb: 1 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.25 }}>
                        推理过程
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{ fontSize: 13, color: "text.secondary", lineHeight: 1.6 }}
                      >
                        {agent.reasoning.length > 300
                          ? agent.reasoning.slice(0, 300) + "…"
                          : agent.reasoning}
                      </Typography>
                    </Box>
                  )}

                  {/* 严重问题 */}
                  {criticalIssues.length > 0 && (
                    <Box sx={{ mb: 1 }}>
                      <Typography variant="caption" color="error.main" sx={{ display: "block", mb: 0.25 }}>
                        严重问题
                      </Typography>
                      <Stack spacing={0.5}>
                        {criticalIssues.map((issue: VerificationIssue, i: number) => (
                          <Alert severity="error" key={i} sx={{ py: 0.5, fontSize: 12 }}>
                            <Typography variant="body2" fontSize={12}>
                              [{issue.location || issue.dimension || "general"}] {issue.description}
                            </Typography>
                            {issue.suggestion && (
                              <Typography variant="caption" color="text.secondary" fontSize={11}>
                                建议：{issue.suggestion}
                              </Typography>
                            )}
                          </Alert>
                        ))}
                      </Stack>
                    </Box>
                  )}

                  {/* 警告项 */}
                  {warnings.length > 0 && (
                    <Box sx={{ mb: 1 }}>
                      <Typography variant="caption" color="warning.main" sx={{ display: "block", mb: 0.25 }}>
                        警告项
                      </Typography>
                      <Stack spacing={0.5}>
                        {warnings.map((warning: VerificationIssue, i: number) => (
                          <Alert severity="warning" key={i} sx={{ py: 0.5, fontSize: 12 }}>
                            <Typography variant="body2" fontSize={12}>
                              {warning.description}
                            </Typography>
                            {warning.suggestion && (
                              <Typography variant="caption" color="text.secondary" fontSize={11}>
                                建议：{warning.suggestion}
                              </Typography>
                            )}
                          </Alert>
                        ))}
                      </Stack>
                    </Box>
                  )}

                  {/* 亮点 */}
                  {agent.highlights && agent.highlights.length > 0 && (
                    <Box>
                      <Typography variant="caption" color="success.main" sx={{ display: "block", mb: 0.25 }}>
                        亮点
                      </Typography>
                      <Stack spacing={0.5}>
                        {agent.highlights.map((h: string, i: number) => (
                          <Box key={i} sx={{ display: "flex", alignItems: "flex-start", gap: 0.5 }}>
                            <CheckIcon sx={{ fontSize: 14, color: "success.main", mt: 0.3 }} />
                            <Typography variant="body2" fontSize={12} color="text.secondary">
                              {h}
                            </Typography>
                          </Box>
                        ))}
                      </Stack>
                    </Box>
                  )}

                  {/* 原始输出 */}
                  {agent.raw_response && Object.keys(agent.raw_response).length > 0 && (
                    <Box sx={{ mt: 1 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.25 }}>
                        原始输出
                      </Typography>
                      <Box
                        sx={{
                          p: 1.5,
                          borderRadius: 1,
                          bgcolor: "background.default",
                          fontSize: 12,
                          fontFamily: "monospace",
                          color: "text.secondary",
                          maxHeight: 240,
                          overflowY: "auto",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          lineHeight: 1.5,
                        }}
                      >
                        {JSON.stringify(agent.raw_response, null, 2)}
                      </Box>
                    </Box>
                  )}

                  {/* 错误信息 */}
                  {agent.error && (
                    <Alert severity="error" sx={{ mt: 1 }}>
                      <Typography variant="body2" fontSize={12}>
                        错误：{agent.error}
                      </Typography>
                    </Alert>
                  )}
                </Box>
              </Collapse>
            </Box>
          );
        })}

        {/* 查看更多 */}
        {hasMore && !showAll && (
          <Button
            size="small"
            onClick={() => setShowAll(true)}
            sx={{ ml: 2, mt: 0.5 }}
          >
            查看全部 {agentItems.length} 个{hasStructuredExecution ? "执行节点" : "Agent"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function ReviewActionModelSelector({
  models,
  modelRefresh,
  actionModelId,
  setActionModelId,
  taskCreativeModelId,
  lastActionModelId,
  lastActionKind,
  reviewModelLabel,
  onRefreshModels,
}: {
  models: ModelOption[];
  modelRefresh: ModelRefreshState;
  actionModelId: string;
  setActionModelId: (value: string) => void;
  taskCreativeModelId?: string;
  lastActionModelId?: string;
  lastActionKind?: string;
  reviewModelLabel?: string;
  onRefreshModels: () => void;
}) {
  const resolvedModelId = models.some((item) => item.id === actionModelId) ? actionModelId : "";

  return (
    <Box
      sx={{
        p: 2,
        borderRadius: 2,
        border: "1px solid",
        borderColor: "divider",
        backgroundColor: "rgba(39, 100, 81, 0.03)",
      }}
    >
      <Stack spacing={1.5}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
          <Typography variant="subtitle2">审核后继续使用的任务创作模型</Typography>
          <Button size="small" variant="outlined" onClick={onRefreshModels}>
            刷新模型
          </Button>
        </Stack>
        <Select
          size="small"
          value={resolvedModelId}
          onChange={(event) => setActionModelId(event.target.value)}
          displayEmpty
          sx={{ maxWidth: 360 }}
        >
          <MenuItem value="">
            <em>请选择审核后继续使用的任务创作模型</em>
          </MenuItem>
          {models.length ? (
            models.map((model) => (
              <MenuItem key={model.id} value={model.id}>
                {(model.display_name || model.id) + (model.provider ? ` · ${model.provider}` : "")}
              </MenuItem>
            ))
          ) : (
            <MenuItem value="" disabled>
              暂无可用模型
            </MenuItem>
          )}
        </Select>
        {!models.length ? (
          <Alert severity="warning">当前没有可用于小说任务流的在线模型，请先刷新模型或检查网关配置。</Alert>
        ) : !resolvedModelId ? (
          <Alert severity="warning">任务创作模型当前不在可用模型列表中，请先手动选择审核后继续使用的任务创作模型。</Alert>
        ) : null}
        <Typography variant="caption" color="text.secondary">
          {formatModelRefreshStatus(modelRefresh)}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          首次进入时可预填当前任务创作模型；模型失效后需手动重新选择。自动审核模型由创建任务时的审核模型配置决定。
        </Typography>
        <Typography variant="caption" color="text.secondary">
          任务创作模型：{taskCreativeModelId || "未设置"}
          {lastActionModelId
            ? ` · 最近一次创作动作模型：${lastActionModelId}${formatActionKindLabel(lastActionKind) ? `（${formatActionKindLabel(lastActionKind)}）` : ""}`
            : ""}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          自动审核模型：{reviewModelLabel || "未设置"}
        </Typography>
      </Stack>
    </Box>
  );
}

function MasterOutlineSection({ storyPlan, readOnly }: { storyPlan: { working_title: string; logline: string; world_notes: string[]; character_notes: string[]; planned_chapter_count?: number | null }; readOnly?: boolean }) {
  const [expanded, setExpanded] = useState(!readOnly);
  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" alignItems="center" spacing={1}>
            <Typography variant="h5" sx={{ flex: 1 }}>
              大纲总纲
            </Typography>
            {readOnly ? <Chip label="已锁定" size="small" color="success" icon={<CheckIcon fontSize="small" />} /> : null}
            <IconButton onClick={() => setExpanded((v) => !v)} size="small">
              <ExpandMoreIcon sx={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }} />
            </IconButton>
          </Stack>
          <Collapse in={expanded}>
            <Stack spacing={2}>
              <Typography variant="h6" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                {storyPlan.working_title}
              </Typography>
              <Typography color="text.secondary">{storyPlan.logline}</Typography>
              <Divider />
              <Typography variant="subtitle1">世界观</Typography>
              <List dense>
                {storyPlan.world_notes.map((note, i) => (
                  <ListItem key={i} disableGutters>
                    <ListItemText primary={note} />
                  </ListItem>
                ))}
              </List>
              <Typography variant="subtitle1">人物</Typography>
              <List dense>
                {storyPlan.character_notes.map((note, i) => (
                  <ListItem key={i} disableGutters>
                    <ListItemText primary={note} />
                  </ListItem>
                ))}
              </List>
              <Typography variant="subtitle1">预计总章数：{storyPlan.planned_chapter_count ?? "未设定"}</Typography>
            </Stack>
          </Collapse>
        </Stack>
      </CardContent>
    </Card>
  );
}

function ConfirmedBatchesSection({ chapters, batchSize }: { chapters: { number: number; title: string; goal: string }[]; batchSize: number }) {
  const batches: { batchNo: number; items: typeof chapters }[] = [];
  for (let i = 0; i < chapters.length; i += batchSize) {
    batches.push({ batchNo: Math.floor(i / batchSize) + 1, items: chapters.slice(i, i + batchSize) });
  }
  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h5">
            章节计划（已确认 {chapters.length} 章）
          </Typography>
          {batches.map((batch) => (
            <Card key={batch.batchNo} variant="outlined">
              <CardContent sx={{ py: 1 }}>
                <Stack direction="row" alignItems="center" spacing={1}>
                  <Typography variant="subtitle2" sx={{ flex: 1 }}>
                    批次 {batch.batchNo}（第{batch.items[0]?.number}-{batch.items[batch.items.length - 1]?.number}章）
                  </Typography>
                  <Chip label="已确认" size="small" color="success" />
                </Stack>
                <List dense>
                  {batch.items.map((ch) => (
                    <ListItem key={ch.number} disableGutters>
                      <ListItemText
                        primary={`第${ch.number}章 ${ch.title}`}
                        secondary={ch.goal}
                      />
                    </ListItem>
                  ))}
                </List>
              </CardContent>
            </Card>
          ))}
        </Stack>
      </CardContent>
    </Card>
  );
}

function PendingBatchSection({ chapters }: { chapters: { number: number; title: string; goal: string }[] }) {
  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" alignItems="center" spacing={1}>
            <Typography variant="h5" sx={{ flex: 1 }}>
              待审核批次（第{chapters[0]?.number}-{chapters[chapters.length - 1]?.number}章）
            </Typography>
            <Chip label="待审核" size="small" color="warning" />
          </Stack>
          <List dense>
            {chapters.map((ch) => (
              <ListItem key={ch.number} disableGutters>
                <ListItemText
                  primary={`第${ch.number}章 ${ch.title}`}
                  secondary={ch.goal}
                />
              </ListItem>
            ))}
          </List>
        </Stack>
      </CardContent>
    </Card>
  );
}

function BatchRollbackControl({ confirmedCount, batchSize, taskId, onRollback }: { confirmedCount: number; batchSize: number; taskId: string; onRollback: () => void }) {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const maxBatch = Math.floor(confirmedCount / batchSize);
  if (maxBatch <= 0) return null;

  async function handleRollback() {
    const keep = parseInt(value, 10);
    if (Number.isNaN(keep) || keep < 0 || keep >= maxBatch) {
      return;
    }
    setLoading(true);
    try {
      await rollbackChapterPlan(taskId, keep);
      onRollback();
    } catch (e) {
      alert(e instanceof Error ? e.message : "回滚失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="h5">回滚章节计划</Typography>
          <Typography variant="body2" color="text.secondary">
            已确认 {confirmedCount} 章（共 {maxBatch} 批），可回滚到任意已确认批次后重新生成。
          </Typography>
          <Stack direction="row" spacing={2} alignItems="center">
            <TextField
              label="保留批次数"
              type="number"
              size="small"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              inputProps={{ min: 0, max: maxBatch - 1 }}
              sx={{ width: 120 }}
            />
            <Button variant="outlined" color="warning" disabled={loading || value === ""} onClick={handleRollback}>
              {loading ? "回滚中..." : "确认回滚"}
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

function ReviewSplitLayout({ main, aside }: { main: ReactNode; aside: ReactNode }) {
  return (
    <Box
      data-testid="review-split-layout"
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "minmax(0, 1fr)",
          lg: "minmax(0, 1fr) minmax(340px, 400px)",
        },
        gap: { xs: 2, md: 3 },
        alignItems: "start",
        minWidth: 0,
      }}
    >
      <Stack data-testid="review-main" spacing={2} sx={{ minWidth: 0 }}>
        {main}
      </Stack>
      <Box data-testid="review-aside" sx={{ minWidth: 0 }}>
        <Stack
          spacing={2}
          sx={{
            minWidth: 0,
            position: { xs: "static", lg: "sticky" },
            top: { lg: 24 },
          }}
        >
          {aside}
        </Stack>
      </Box>
    </Box>
  );
}

function OutlineReview({
  review,
  outlineMarkdown,
  comment,
  setComment,
  submitting,
  onDecision,
  error,
  models,
  modelRefresh,
  actionModelId,
  setActionModelId,
  onRefreshModels,
  taskId,
  onReload,
}: {
  review: ReviewResponse;
  outlineMarkdown: string;
  comment: string;
  setComment: (v: string) => void;
  submitting: boolean;
  onDecision: (approved: boolean) => void;
  error: string;
  models: ModelOption[];
  modelRefresh: ModelRefreshState;
  actionModelId: string;
  setActionModelId: (v: string) => void;
  onRefreshModels: () => void;
  taskId: string;
  onReload: () => void;
}) {
  const revisionCount = review.revision_count ?? 0;
  const hasValidActionModel = models.some((item) => item.id === actionModelId);
  const outlineBatch = review.outline_batch;
  const phase = outlineBatch?.phase ?? "master";
  const batchSize = outlineBatch?.batch_size ?? 20;
  const completedCount = outlineBatch?.completed_count ?? 0;
  const totalCount = outlineBatch?.total_count ?? 0;
  const currentBatchPlans = outlineBatch?.current_batch_plans ?? [];

  // 优先使用后端返回的结构化 story_plan 数据
  const storyPlan = review.story_plan ?? {
    working_title: review.meta.title || "",
    logline: review.summary || "",
    world_notes: [] as string[],
    character_notes: [] as string[],
    planned_chapter_count: totalCount || null,
  };

  const isMasterPhase = phase === "master";
  const isBatchPhase = phase === "chapter_batches";

  return (
    <ReviewSplitLayout
      main={
        <>
          <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            {isMasterPhase ? "大纲审核 · 总纲阶段" : `大纲审核 · 章节计划阶段（已确认 ${completedCount}/${totalCount} 章）`}
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip label={review.meta.title || review.meta.task_id} size="small" />
            <Chip label={`版本 ${review.review_version}`} size="small" variant="outlined" />
            <Chip label={`审核第 ${revisionCount + 1} 轮`} size="small" variant="outlined" />
            <Chip label={review.review_type} size="small" variant="outlined" />
          </Stack>

          <MasterOutlineSection storyPlan={storyPlan} readOnly={isBatchPhase} />

          {isBatchPhase && (
            <>
              {completedCount > 0 && outlineMarkdown ? (
                <ConfirmedBatchesSection
                  chapters={[]}
                  batchSize={batchSize}
                />
              ) : null}

              {currentBatchPlans.length > 0 ? (
                <PendingBatchSection chapters={currentBatchPlans} />
              ) : (
                <Alert severity="info">正在生成下一批章节计划...</Alert>
              )}

              <BatchRollbackControl
                confirmedCount={completedCount}
                batchSize={batchSize}
                taskId={taskId}
                onRollback={onReload}
              />
            </>
          )}

          {isMasterPhase && (
            <Card>
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="h5">大纲内容</Typography>
                  {outlineMarkdown ? (
                    <MarkdownContent variant="outline">
                      {outlineMarkdown}
                    </MarkdownContent>
                  ) : (
                    <Alert severity="info">暂无大纲内容。</Alert>
                  )}
                </Stack>
              </CardContent>
            </Card>
          )}
        </>
      }
      aside={
        <>
          <AgentTracePanel trace={review.auto_review_trace ?? []} />
          {error ? <ValidationErrorAlert message={error} modelId={actionModelId} /> : null}
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">审核操作</Typography>
                <ReviewHistory history={review.review_history} />
                <ReviewActionModelSelector
                  models={models}
                  modelRefresh={modelRefresh}
                  actionModelId={actionModelId}
                  setActionModelId={setActionModelId}
                  taskCreativeModelId={review.meta.creative_model_id || review.meta.model_id}
                  lastActionModelId={review.meta.last_action_model_id}
                  lastActionKind={review.meta.last_action_kind}
                  reviewModelLabel={formatReviewModelLabel(review)}
                  onRefreshModels={onRefreshModels}
                />
                <TextField
                  label="审核意见"
                  multiline
                  minRows={3}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="例如：通过；或者要求收束得更克制一些。"
                />
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <Button disabled={submitting || !hasValidActionModel} variant="contained" onClick={() => onDecision(true)}>
                    {isMasterPhase ? "通过并进入章节计划设计" : "通过本批"}
                  </Button>
                  <Button disabled={submitting || !hasValidActionModel} variant="outlined" color="error" onClick={() => onDecision(false)}>
                    {isMasterPhase ? "拒绝并进入大纲修订" : "驳回重算本批"}
                  </Button>
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  {isMasterPhase
                    ? "通过后将进入章节计划分步设计；拒绝后将进入大纲修订并回到工作台。"
                    : "通过后将生成下一批或进入正文编写；驳回后将重新生成本批章节计划。"}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </>
      }
    />
  );
}

function ChapterPairReview({
  review,
  comment,
  setComment,
  submitting,
  onDecision,
  error,
  models,
  modelRefresh,
  actionModelId,
  setActionModelId,
  onRefreshModels,
}: {
  review: ReviewResponse;
  comment: string;
  setComment: (v: string) => void;
  submitting: boolean;
  onDecision: (approved: boolean) => void;
  error: string;
  models: ModelOption[];
  modelRefresh: ModelRefreshState;
  actionModelId: string;
  setActionModelId: (v: string) => void;
  onRefreshModels: () => void;
}) {
  const chapters = review.chapter_pair || [];
  const batchIndex = review.batch_index ?? 0;
  const completed = review.completed_count ?? 0;
  const total = review.total_chapters ?? 0;
  const revisionCount = review.chapter_pair_revision_count ?? 0;
  const batchEnd = Math.min(batchIndex + Math.max(chapters.length, 1), total);
  const hasValidActionModel = models.some((item) => item.id === actionModelId);

  return (
    <ReviewSplitLayout
      main={
        <>
          <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            章节批次审核
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip label={review.meta.title || review.meta.task_id} size="small" />
            <Chip
              label={batchEnd <= batchIndex + 1 ? `第 ${batchIndex + 1} 章` : `第 ${batchIndex + 1}-${batchEnd} 章`}
              size="small"
              color="primary"
            />
            <Chip label={`${completed}/${total} 章`} size="small" variant="outlined" />
            {revisionCount > 0 && (
              <Chip label={`修订第 ${revisionCount + 1} 轮`} size="small" variant="outlined" color="warning" />
            )}
          </Stack>

          <Card>
            <CardContent>
              <Stack spacing={1}>
                <Typography variant="h5">进度</Typography>
                <LinearProgress
                  variant="determinate"
                  value={total > 0 ? (completed / total) * 100 : 0}
                  sx={{ height: 8, borderRadius: 4 }}
                />
                <Typography variant="body2" color="text.secondary">
                  已完成 {completed} / {total} 章，正在审核
                  {batchEnd <= batchIndex + 1 ? ` 第 ${batchIndex + 1} 章` : ` 第 ${batchIndex + 1}-${batchEnd} 章`}
                </Typography>
              </Stack>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">审核摘要</Typography>
                <Typography>{review.summary || review.meta.summary || "请审核本批章节是否符合大纲要求。"}</Typography>
              </Stack>
            </CardContent>
          </Card>

          {chapters.map((chapter) => (
            <Card key={chapter.number}>
              <CardContent>
                <Stack spacing={2}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="h5">
                      第 {chapter.number} 章：{chapter.title}
                    </Typography>
                    <Chip label={chapter.summary} size="small" variant="outlined" />
                  </Stack>
                  <Divider />
                  <MarkdownContent variant="outline">
                    {chapter.content}
                  </MarkdownContent>
                </Stack>
              </CardContent>
            </Card>
          ))}
        </>
      }
      aside={
        <>
          <AgentTracePanel trace={review.auto_review_trace ?? []} />
          {error ? <ValidationErrorAlert message={error} modelId={actionModelId} /> : null}
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">审核操作</Typography>
                <ReviewHistory history={review.review_history} />
                <ReviewActionModelSelector
                  models={models}
                  modelRefresh={modelRefresh}
                  actionModelId={actionModelId}
                  setActionModelId={setActionModelId}
                  taskCreativeModelId={review.meta.creative_model_id || review.meta.model_id}
                  lastActionModelId={review.meta.last_action_model_id}
                  lastActionKind={review.meta.last_action_kind}
                  reviewModelLabel={formatReviewModelLabel(review)}
                  onRefreshModels={onRefreshModels}
                />
                <TextField
                  label="审核意见"
                  multiline
                  minRows={3}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="例如：通过；或者第 3 段逻辑不够顺畅，请加强。"
                />
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <Button disabled={submitting || !hasValidActionModel} variant="contained" onClick={() => onDecision(true)}>
                    通过并进入下一步
                  </Button>
                  <Button disabled={submitting || !hasValidActionModel} variant="outlined" color="error" onClick={() => onDecision(false)}>
                    拒绝并返回工作台
                  </Button>
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  通过后系统会自动判断是返回工作台继续创作，还是进入全文验证；拒绝后将返回工作台等待你重新发起继续创作。
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </>
      }
    />
  );
}

function VerificationReview({
  review,
  comment,
  setComment,
  submitting,
  onDecision,
  error,
  models,
  modelRefresh,
  actionModelId,
  setActionModelId,
  onRefreshModels,
}: {
  review: ReviewResponse;
  comment: string;
  setComment: (v: string) => void;
  submitting: boolean;
  onDecision: (approved: boolean) => void;
  error: string;
  models: ModelOption[];
  modelRefresh: ModelRefreshState;
  actionModelId: string;
  setActionModelId: (v: string) => void;
  onRefreshModels: () => void;
}) {
  const report = review.verification_report || {};
  const issues = report.issues || [];
  const score = report.overall_score ?? 0;
  const revisionCount = review.verification_revision_count ?? 0;
  const hasValidActionModel = models.some((item) => item.id === actionModelId);

  const scoreColor = score >= 80 ? "success" : score >= 60 ? "warning" : "error";

  return (
    <ReviewSplitLayout
      main={
        <>
          <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            验证审核
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip label={review.meta.title || review.meta.task_id} size="small" />
            <Chip label="全文验证" size="small" color="primary" />
            {revisionCount > 0 && (
              <Chip label={`修订第 ${revisionCount + 1} 轮`} size="small" variant="outlined" color="warning" />
            )}
          </Stack>

          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">验证摘要</Typography>
                <Typography>{review.summary || review.meta.summary || "全文一致性验证已完成。"}</Typography>
                <Box>
                  <Typography variant="h2" color={`${scoreColor}.main`}>
                    {score}
                  </Typography>
                  <Typography color="text.secondary">总分（0–100）</Typography>
                </Box>
              </Stack>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">发现的问题</Typography>
                {issues.length === 0 ? (
                  <Alert severity="success">未发现问题，全文一致性良好。</Alert>
                ) : (
                  <List dense>
                    {issues.map((issue, index) => (
                      <ListItem key={index} disableGutters>
                        <ListItemText
                          primary={
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Chip
                                label={issue.severity}
                                size="small"
                                color={
                                  issue.severity === "critical"
                                    ? "error"
                                    : issue.severity === "warning"
                                      ? "warning"
                                      : "info"
                                }
                              />
                              <Typography variant="body2">{issue.location}</Typography>
                            </Stack>
                          }
                          secondary={
                            <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                              <Typography variant="body2" color="text.secondary">
                                {issue.description}
                              </Typography>
                              <Typography variant="caption" color="primary">
                                建议：{issue.suggestion}
                              </Typography>
                            </Stack>
                          }
                        />
                      </ListItem>
                    ))}
                  </List>
                )}
              </Stack>
            </CardContent>
          </Card>
        </>
      }
      aside={
        <>
          <AgentTracePanel trace={review.auto_review_trace ?? []} />
          {error ? <ValidationErrorAlert message={error} modelId={actionModelId} /> : null}
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">审核操作</Typography>
                <ReviewHistory history={review.review_history} />
                <ReviewActionModelSelector
                  models={models}
                  modelRefresh={modelRefresh}
                  actionModelId={actionModelId}
                  setActionModelId={setActionModelId}
                  taskCreativeModelId={review.meta.creative_model_id || review.meta.model_id}
                  lastActionModelId={review.meta.last_action_model_id}
                  lastActionKind={review.meta.last_action_kind}
                  reviewModelLabel={formatReviewModelLabel(review)}
                  onRefreshModels={onRefreshModels}
                />
                <TextField
                  label="审核意见"
                  multiline
                  minRows={3}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="例如：通过；或者人物前后不一致，请修复后再审。"
                />
                <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                  <Button disabled={submitting || !hasValidActionModel} variant="contained" onClick={() => onDecision(true)}>
                    通过并完成任务
                  </Button>
                  <Button disabled={submitting || !hasValidActionModel} variant="outlined" color="error" onClick={() => onDecision(false)}>
                    拒绝并进入验证修复
                  </Button>
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  通过后任务会进入收尾完成流程，并在完成后进入结果页；拒绝后将进入验证修复流程，并留在当前审核链路。
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </>
      }
    />
  );
}

export default function TaskReviewClient({ taskId }: { taskId?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const resolvedTaskId = taskId || searchParams.get("id") || "";
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [outlineMarkdown, setOutlineMarkdown] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelRefresh, setModelRefresh] = useState<ModelRefreshState>({ loading: false, error: "" });
  const [actionModelId, setActionModelId] = useState("");
  const [recoveryDialogOpen, setRecoveryDialogOpen] = useState(false);
  const [selectedRecoveryAction, setSelectedRecoveryAction] = useState<RecoveryMode>("recover_to_stable");
  const [recoveryModelId, setRecoveryModelId] = useState("");
  const [reviewInvalidated, setReviewInvalidated] = useState(false);
  const currentActionModelIdRef = useRef("");
  const currentTaskModelIdRef = useRef("");
  const currentModelOptionsRef = useRef<ModelOption[]>([]);
  const actionModelInitializedRef = useRef(false);
  const recoveryModelInitializedRef = useRef(false);

  const loadReview = useCallback(async () => {
    if (!resolvedTaskId) {
      setError("缺少任务 ID");
      setReview(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const nextReview = await getReview(resolvedTaskId);
      setReview(nextReview);
      setOutlineMarkdown(nextReview.outline_markdown ?? "");
      setError("");

      if (!nextReview.outline_markdown && nextReview.outline_md_ref) {
        const markdown = await fetchTextRef(nextReview.outline_md_ref);
        setOutlineMarkdown(markdown);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "读取审核信息失败");
    } finally {
      setLoading(false);
    }
  }, [resolvedTaskId]);

  useEffect(() => {
    void loadReview();
  }, [loadReview]);

  const currentTaskModelId = resolveReviewTaskModelId(review);

  useEffect(() => {
    currentActionModelIdRef.current = actionModelId;
  }, [actionModelId]);

  useEffect(() => {
    currentTaskModelIdRef.current = currentTaskModelId;
  }, [currentTaskModelId]);

  useEffect(() => {
    currentModelOptionsRef.current = models;
  }, [models]);

  const loadModels = useCallback(async (refresh = false) => {
    try {
      setModelRefresh((current) => ({ ...current, loading: true, error: "" }));
      const catalog = await getModelCatalog({ refresh });
      const nextModels = selectNovelTaskModels(normalizeModelOptions(catalog.data ?? []));
      const currentEffectiveModelId = currentActionModelIdRef.current || currentTaskModelIdRef.current;
      const nextSelection = resolveSelectionAfterRefresh({
        currentModelId: currentEffectiveModelId,
        availableModels: nextModels,
      });
      setModels(nextModels);
      setModelRefresh((current) => ({
        ...current,
        loading: false,
        error: "",
        attemptedRefresh: current.attemptedRefresh || refresh,
        fetchedAt: catalog.meta?.fetched_at,
        cacheAgeSeconds: catalog.meta?.cache_age_seconds,
        cacheTtlSeconds: catalog.meta?.cache_ttl_seconds,
        cached: catalog.meta?.cached,
        invalidated: refresh && nextSelection.invalidated,
        invalidatedModelLabel:
          refresh && nextSelection.invalidated
            ? currentModelOptionsRef.current.find((option) => option.id === currentEffectiveModelId)?.display_name ||
              currentEffectiveModelId ||
              undefined
            : undefined,
      }));
    } catch (loadError) {
      setModels([]);
      setModelRefresh((current) => ({
        ...current,
        loading: false,
        error: loadError instanceof Error ? loadError.message : "读取模型列表失败",
        attemptedRefresh: current.attemptedRefresh || refresh,
      }));
    }
  }, []);

  useEffect(() => {
    void loadModels(false);
  }, [loadModels]);

  useEffect(() => {
    setActionModelId("");
    setModelRefresh({ loading: false, error: "" });
    setRecoveryDialogOpen(false);
    setSelectedRecoveryAction("recover_to_stable");
    setRecoveryModelId("");
    setReviewInvalidated(false);
    actionModelInitializedRef.current = false;
    recoveryModelInitializedRef.current = false;
  }, [resolvedTaskId]);

  const resolvedActionModelId = models.some((item) => item.id === actionModelId) ? actionModelId : "";
  const primaryRecoveryAction = derivePrimaryRecoveryAction(review);
  const recoveryPreview = resolveRecoveryPreview(review, selectedRecoveryAction);
  const recoverySelectableModels = filterRecoveryModels(models, recoveryPreview?.allowed_model_ids);
  const recoveryTaskCreativeModelId =
    recoveryPreview?.creative_model_id ||
    currentTaskModelId ||
    "";

  useEffect(() => {
    if (actionModelId) {
      if (models.some((item) => item.id === actionModelId)) {
        return;
      }
      localStorage.removeItem("novel-agent:action-model-id");
      setActionModelId("");
      return;
    }
    if (actionModelInitializedRef.current || !models.length) {
      return;
    }
    actionModelInitializedRef.current = true;
    const savedModelId = localStorage.getItem("novel-agent:action-model-id");
    if (savedModelId && models.some((item) => item.id === savedModelId)) {
      setActionModelId(savedModelId);
      return;
    }
    if (currentTaskModelId && models.some((item) => item.id === currentTaskModelId)) {
      setActionModelId(currentTaskModelId);
      return;
    }
    setActionModelId("");
  }, [actionModelId, currentTaskModelId, models]);

  const hasValidActionModel = Boolean(resolvedActionModelId);

  function handleActionModelChange(nextModelId: string) {
    actionModelInitializedRef.current = true;
    setActionModelId(nextModelId);
    if (nextModelId) {
      localStorage.setItem("novel-agent:action-model-id", nextModelId);
    } else {
      localStorage.removeItem("novel-agent:action-model-id");
    }
    setModelRefresh((current) => ({ ...current, invalidated: false, invalidatedModelLabel: undefined }));
  }

  useEffect(() => {
    if (!recoveryDialogOpen) {
      return;
    }
    if (recoveryModelId) {
      if (recoverySelectableModels.some((item) => item.id === recoveryModelId)) {
        return;
      }
      setRecoveryModelId("");
      return;
    }
    if (recoveryModelInitializedRef.current || !recoverySelectableModels.length) {
      return;
    }
    recoveryModelInitializedRef.current = true;
    if (recoveryTaskCreativeModelId && recoverySelectableModels.some((item) => item.id === recoveryTaskCreativeModelId)) {
      setRecoveryModelId(recoveryTaskCreativeModelId);
      return;
    }
    setRecoveryModelId("");
  }, [recoveryDialogOpen, recoveryModelId, recoverySelectableModels, recoveryTaskCreativeModelId]);

  function handleOpenRecoveryDialog() {
    const nextAction =
      primaryRecoveryAction?.action ||
      (review?.recommended_action === "recover_to_stable" || review?.recommended_action === "restart_from_input"
        ? review.recommended_action
        : (review?.recovery_options?.find((item) => item.available)?.action ?? null));
    if (!nextAction) {
      return;
    }
    setSelectedRecoveryAction(nextAction);
    setRecoveryModelId("");
    setRecoveryDialogOpen(true);
  }

  async function handleRecover() {
    try {
      setSubmitting(true);
      await recoverTask(resolvedTaskId, {
        recovery_mode: selectedRecoveryAction,
        model_id: recoveryModelId || undefined,
      });
      setError("");
      setRecoveryDialogOpen(false);
      if (selectedRecoveryAction === "restart_from_input") {
        setReviewInvalidated(true);
        return;
      }
      await loadReview();
      router.refresh();
    } catch (recoverError) {
      const rawMessage = recoverError instanceof Error ? recoverError.message : "执行恢复失败";
      const message = normalizeTaskActionErrorMessage(rawMessage);
      setError(message);
      if (message !== rawMessage) {
        router.push(workspaceHref(resolvedTaskId));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDecision(approved: boolean) {
    if (!hasValidActionModel) {
      setError("任务创作模型当前不可用，请先手动选择本次执行模型。");
      return;
    }
    try {
      setSubmitting(true);
      const nextTask = await resumeTask(resolvedTaskId, approved, comment, resolvedActionModelId || undefined);
      setError("");
      if (nextTask.status === "completed") {
        router.push(resultHref(resolvedTaskId));
      } else if (approved && nextTask.status === "ready_for_batch") {
        router.push(workspaceHref(resolvedTaskId));
      } else if (
        nextTask.status === "waiting_outline_review" ||
        nextTask.status === "waiting_chapter_review" ||
        nextTask.status === "waiting_verification_review"
      ) {
        await loadReview();
        router.refresh();
      } else {
        router.push(workspaceHref(resolvedTaskId));
      }
    } catch (submitError) {
      const rawMessage = submitError instanceof Error ? submitError.message : "提交审核失败";
      const message = normalizeTaskActionErrorMessage(rawMessage);
      setError(message);
      if (message !== rawMessage) {
        router.push(workspaceHref(resolvedTaskId));
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loading && !review) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Box sx={{ py: 6 }}>
          <Typography>正在载入审核信息...</Typography>
        </Box>
      </Container>
    );
  }

  if (!review) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2} sx={{ py: 6 }}>
          <Alert severity="error">{error || "读取审核信息失败"}</Alert>
          <Box>
            <Button variant="outlined" onClick={() => void loadReview()}>
              重新加载
            </Button>
          </Box>
        </Stack>
      </Container>
    );
  }

  if (reviewInvalidated) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Stack spacing={3} className="page-fade-in">
          <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
            <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
              <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
                首页
              </Typography>
            </Link>
            <Link href={workspaceHref(resolvedTaskId)} style={{ color: "inherit", textDecoration: "none" }}>
              <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
                工作台
              </Typography>
            </Link>
            <Typography variant="body2">审核上下文已失效</Typography>
          </Breadcrumbs>
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h4" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                  当前审核上下文已失效
                </Typography>
                <Alert severity="info">任务已按原始输入重新开始，当前审核内容不再有效。</Alert>
                <Box>
                  <Button variant="contained" onClick={() => router.push(workspaceHref(resolvedTaskId))}>
                    打开工作台
                  </Button>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </Container>
    );
  }

  const reviewType = review.review_type || "outline_review";
  const outlinePhase = review.outline_batch?.phase ?? "master";
  const activeStep =
    reviewType === "outline_review"
      ? outlinePhase === "chapter_batches"
        ? 3
        : 2
      : reviewType === "chapter_pair_review"
        ? 3
        : reviewType === "verification_review"
          ? 3
          : 2;
  const steps =
    reviewType === "outline_review"
      ? outlinePhase === "chapter_batches"
        ? OUTLINE_BATCH_STEPS
        : OUTLINE_STEPS
      : reviewType === "chapter_pair_review"
        ? CHAPTER_STEPS
        : VERIFY_STEPS;

  const breadcrumbLabel =
    reviewType === "outline_review"
      ? "大纲审核"
      : reviewType === "chapter_pair_review"
        ? "章节审核"
        : reviewType === "verification_review"
          ? "验证审核"
          : "审核";

  return (
    <ProjectShell
      breadcrumbs={[
        { label: "首页", href: "/" },
        { label: "工作台", href: workspaceHref(resolvedTaskId) },
        { label: breadcrumbLabel },
      ]}
      title={breadcrumbLabel}
      metaItems={[
        { label: review.meta.title || resolvedTaskId },
        { label: review.meta.status, variant: "outlined" },
        ...(currentTaskModelId ? [{ label: `任务创作模型 ${currentTaskModelId}`, variant: "outlined" as const }] : []),
      ]}
      stageNav={<StageNav stages={steps} activeStep={activeStep} />}
      maxWidth="lg"
    >

        {error ? <ValidationErrorAlert message={error} modelId={currentTaskModelId} /> : null}
        {review.state_reconciled ? (
          <Alert severity="info">
            {review.reconciliation_summary || "当前审核状态已自动校正到最新稳定状态。"}
          </Alert>
        ) : null}
        {primaryRecoveryAction ? (
          <Card>
            <CardContent>
              <Stack spacing={2}>
                <Typography variant="h5">恢复与修复</Typography>
                <Typography variant="body2" color="text.secondary">
                  {primaryRecoveryAction.label === "查看恢复方案"
                    ? "当前没有可直接回填的稳定阶段，请先查看恢复方案，再决定是否改为按原始输入重新开始。"
                    : `推荐动作：${primaryRecoveryAction.label}。${
                        review.recommended_action ? `后端建议动作：${primaryRecoveryAction.label}。` : ""
                      }`}
                </Typography>
                <Box>
                  <Button variant="contained" disabled={submitting} onClick={handleOpenRecoveryDialog}>
                    {submitting ? "执行中..." : primaryRecoveryAction.label}
                  </Button>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        ) : null}

        {/* 条件渲染审核内容 */}
        {reviewType === "outline_review" && (
          <OutlineReview
            review={review}
            outlineMarkdown={outlineMarkdown}
            comment={comment}
            setComment={setComment}
            submitting={submitting}
            onDecision={handleDecision}
            error={error}
            models={models}
            modelRefresh={modelRefresh}
            actionModelId={actionModelId}
            setActionModelId={handleActionModelChange}
            onRefreshModels={() => void loadModels(true)}
            taskId={resolvedTaskId}
            onReload={loadReview}
          />
        )}

        {reviewType === "chapter_pair_review" && (
          <ChapterPairReview
            review={review}
            comment={comment}
            setComment={setComment}
            submitting={submitting}
            onDecision={handleDecision}
            error={error}
            models={models}
            modelRefresh={modelRefresh}
            actionModelId={actionModelId}
            setActionModelId={handleActionModelChange}
            onRefreshModels={() => void loadModels(true)}
          />
        )}

        {reviewType === "verification_review" && (
          <VerificationReview
            review={review}
            comment={comment}
            setComment={setComment}
            submitting={submitting}
            onDecision={handleDecision}
            error={error}
            models={models}
            modelRefresh={modelRefresh}
            actionModelId={actionModelId}
            setActionModelId={handleActionModelChange}
            onRefreshModels={() => void loadModels(true)}
          />
        )}

        <RecoveryDialog
          open={recoveryDialogOpen}
          recovery={review}
          models={models}
          selectedAction={selectedRecoveryAction}
          selectedModelId={recoveryModelId}
          taskCreativeModelId={recoveryTaskCreativeModelId}
          submitting={submitting}
          onActionChange={(action) => {
            setSelectedRecoveryAction(action);
            setRecoveryModelId("");
          }}
        onModelChange={(modelId) => {
          recoveryModelInitializedRef.current = true;
          setRecoveryModelId(modelId);
        }}
          onCancel={() => setRecoveryDialogOpen(false)}
          onConfirm={() => void handleRecover()}
        />
    </ProjectShell>
  );
}
