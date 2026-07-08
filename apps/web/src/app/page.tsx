"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Grid,
  MenuItem,
  Pagination,
  Select,
  Skeleton,
  Snackbar,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { ArrowForward as ArrowForwardIcon, Replay as ReplayIcon, Delete as DeleteIcon } from "@mui/icons-material";
import { deleteTask, getDashboard, getModelCatalog, getProtocolSettings, normalizeModelOptions, setModelProtocol, updateDefaultModel } from "@/lib/api";
import { selectNovelTaskModels } from "@/lib/model-options.mjs";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { newProjectHref } from "@/lib/task-routes";
import { DashboardResponse, ModelOption, ModelRefreshState, TaskCardSummary, TaskStatus } from "@/lib/types";
import { formatModelRefreshStatus } from "@/features/task-models/model-refresh-state.mjs";
import { getValidationLinkFromError } from "@/features/chat/model-validation-state.mjs";
import { resolveTaskHref } from "@/features/task-dashboard/task-card-state.mjs";

const statusLabelMap: Record<TaskStatus, string> = {
  created: "待启动",
  sources_ingested: "已入库",
  planning: "规划中",
  waiting_outline_review: "待大纲审核",
  ready_for_batch: "可继续创作",
  drafting: "正文生成中",
  waiting_manual_action: "待人工处理",
  assembling: "结果整理中",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
  waiting_chapter_review: "待章节审核",
  waiting_verification_review: "待验证审核",
};

const DELETABLE_STATUSES: TaskStatus[] = [
  "created",
  "sources_ingested",
  "waiting_outline_review",
  "ready_for_batch",
  "waiting_chapter_review",
  "waiting_verification_review",
  "failed",
  "cancelled",
];

function isDeletable(status: TaskStatus): boolean {
  return DELETABLE_STATUSES.includes(status);
}

function getDeletePrompt(status: TaskStatus): string {
  switch (status) {
    case "waiting_chapter_review":
    case "waiting_verification_review":
      return "该任务已有章节生成，删除后将丢失所有已生成内容。确认删除？";
    case "waiting_outline_review":
      return "该任务大纲已生成，删除后将丢失大纲内容。确认删除？";
    case "created":
    case "sources_ingested":
      return "该任务尚未开始编写，确认删除？";
    case "failed":
      return "该任务执行失败，确认删除？";
    case "cancelled":
      return "确认删除该已取消的任务？";
    case "ready_for_batch":
      return "该任务已有部分进度，删除后将丢失已生成内容。确认删除？";
    default:
      return "确认删除该任务？此操作不可恢复。";
  }
}

// 首页作品库项目卡片
function TaskListItem({ task, onDelete }: { task: TaskCardSummary; onDelete?: (taskId: string) => void }) {
  const isFailed = task.status === "failed";
  const deletable = isDeletable(task.status);
  const taskTypeLabel = formatTaskTypeLabel({
    creativeMode: task.creative_mode,
    novelSize: task.novel_size,
    mode: task.mode,
  });
  return (
    <Card
      data-testid="project-card"
      variant="outlined"
      sx={{
        borderRadius: 2,
        transition: "border-color 0.2s, box-shadow 0.2s",
        "&:hover": { borderColor: "primary.main", boxShadow: 2 },
      }}
    >
      <CardContent sx={{ p: 2.25, "&:last-child": { pb: 2.25 } }}>
        <Stack spacing={1.5} sx={{ minWidth: 0 }}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1.25}
            justifyContent="space-between"
            alignItems={{ xs: "stretch", sm: "flex-start" }}
          >
            <Stack spacing={0.75} sx={{ minWidth: 0, flex: 1 }}>
              <Typography
                variant="h6"
                sx={{
                  fontWeight: 700,
                  minWidth: 0,
                  lineHeight: 1.25,
                  overflowWrap: "anywhere",
                }}
              >
                {task.title || task.task_id}
              </Typography>
              <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75 }}>
                <Chip label={statusLabelMap[task.status] ?? task.status} size="small" color={isFailed ? "error" : "default"} />
                <Chip label={task.current_stage} size="small" variant="outlined" />
                <Chip label={taskTypeLabel} size="small" variant="outlined" />
              </Stack>
            </Stack>
            <Box
              sx={{
                display: "flex",
                flexWrap: "wrap",
                gap: 1,
                justifyContent: { xs: "flex-start", sm: "flex-end" },
                flexShrink: 0,
              }}
            >
              <Button
                component={Link}
                href={resolveTaskHref(task)}
                size="small"
                variant="contained"
                endIcon={<ArrowForwardIcon />}
                sx={{ flexShrink: 0, minWidth: "auto", px: 1.25 }}
              >
                进入项目
              </Button>
              {isFailed && (
                <Button
                  component={Link}
                  href={`${newProjectHref()}?retry_from=${encodeURIComponent(task.task_id)}`}
                  size="small"
                  color="warning"
                  startIcon={<ReplayIcon />}
                  variant="outlined"
                  sx={{ flexShrink: 0, minWidth: "auto", px: 1.25 }}
                >
                  重新创建
                </Button>
              )}
              {deletable && onDelete && (
                <Button
                  size="small"
                  color="error"
                  startIcon={<DeleteIcon />}
                  onClick={() => onDelete(task.task_id)}
                  variant="outlined"
                  sx={{ flexShrink: 0, minWidth: "auto", px: 1.25 }}
                >
                  删除
                </Button>
              )}
            </Box>
          </Stack>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{
              display: "-webkit-box",
              overflow: "hidden",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 2,
              overflowWrap: "anywhere",
            }}
          >
            {task.summary}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 0.5, minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>
              更新时间 {new Date(task.updated_at).toLocaleString()}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ minWidth: 0, overflowWrap: "anywhere" }}>
              ID {task.task_id}
            </Typography>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}

// Tab 分组 + 独立滚动列表 + 固定分页器
const PAGE_SIZE = 5;
const LIST_MAX_HEIGHT = 480;

function TaskTabPanel({ dashboard, onDelete }: { dashboard: DashboardResponse; onDelete?: (taskId: string) => void }) {
  const [activeTab, setActiveTab] = useState(0);
  const [page, setPage] = useState(1);

  const tabConfig = [
    { label: "待处理", total: dashboard.continue_tasks.length, list: dashboard.continue_tasks },
    { label: "运行中", total: dashboard.running_tasks.length, list: dashboard.running_tasks },
    { label: "失败", total: dashboard.failed_tasks.length, list: dashboard.failed_tasks },
    { label: "已完成", total: (dashboard.completed_tasks ?? []).length, list: dashboard.completed_tasks ?? [] },
  ];

  const current = tabConfig[activeTab];
  const totalPages = Math.max(1, Math.ceil(current.total / PAGE_SIZE));
  const pagedList = current.list.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const projectTotal = (dashboard.continue_total ?? dashboard.continue_tasks.length)
    + (dashboard.running_total ?? dashboard.running_tasks.length)
    + (dashboard.failed_total ?? dashboard.failed_tasks.length)
    + (dashboard.completed_total ?? dashboard.completed_tasks?.length ?? 0);

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
    setPage(1);
  };

  const emptyTexts = ["当前没有需要人工继续处理的任务。", "当前没有运行中的任务。", "当前没有失败任务。", "当前没有已完成的任务。"];

  return (
    <Box
      sx={{
        border: 1,
        borderColor: "divider",
        borderRadius: 2,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        bgcolor: "background.paper",
      }}
    >
      <Box sx={{ px: 2, py: 1.75, borderBottom: 1, borderColor: "divider", flexShrink: 0 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", sm: "center" }}
        >
          <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)", fontWeight: 700 }}>
            作品库
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {projectTotal} 个项目
          </Typography>
        </Stack>
      </Box>

      <Box sx={{ borderBottom: 1, borderColor: "divider", flexShrink: 0 }}>
        <Tabs
          value={activeTab}
          onChange={handleTabChange}
          variant="scrollable"
          allowScrollButtonsMobile
          sx={{
            minHeight: 48,
            px: 1,
            "& .MuiTab-root": { minHeight: 48, textTransform: "none", fontWeight: 500 },
          }}
        >
          {tabConfig.map((tab) => (
            <Tab key={tab.label} label={`${tab.label} (${tab.total})`} />
          ))}
        </Tabs>
      </Box>

      {/* 列表区域独立滚动 */}
      <Box
        sx={{
          overflowY: "auto",
          maxHeight: LIST_MAX_HEIGHT,
          px: 2,
          py: 1.5,
          flex: 1,
        }}
      >
        {pagedList.length ? (
          <Stack spacing={1.5}>
            {pagedList.map((task) => (
              <TaskListItem key={task.task_id} task={task} onDelete={onDelete} />
            ))}
          </Stack>
        ) : (
          <Typography color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
            {emptyTexts[activeTab]}
          </Typography>
        )}
      </Box>

      {current.total > PAGE_SIZE && (
        <Box
          sx={{
            flexShrink: 0,
            display: "flex",
            justifyContent: "center",
            py: 1.5,
            borderTop: 1,
            borderColor: "divider",
          }}
        >
          <Pagination
            count={totalPages}
            page={page}
            onChange={(_, p) => setPage(p)}
            size="small"
            shape="rounded"
          />
        </Box>
      )}
    </Box>
  );
}

// 侧边栏 - 统计卡片
function SidebarStats({
  dashboard,
  models,
  modelRefresh,
  onModelChange,
  onRefreshModels,
  protocolOverrides,
  onToggleProtocol,
}: {
  dashboard: DashboardResponse;
  models: ModelOption[];
  modelRefresh: ModelRefreshState;
  onModelChange: (modelId: string) => void;
  onRefreshModels: () => void;
  protocolOverrides: Record<string, string>;
  onToggleProtocol: (modelId: string, currentProtocol: string) => void;
}) {
  const stats = [
    {
      label: "活动运行",
      value: dashboard.running_tasks.length,
      sub: `${dashboard.system_summary?.active_runs ?? 0} 接口统计`,
    },
    {
      label: "归档任务",
      value: dashboard.system_summary?.archived_runs ?? 0,
      sub: "已归档运行数",
    },
  ];

  const currentDefault = dashboard.model_summary?.default_model ?? "";
  const selectableModels: ModelOption[] = selectNovelTaskModels(models);
  const selectValue = selectableModels.some((item) => item.id === currentDefault) ? currentDefault : "";

  return (
    <Stack spacing={2}>
      {stats.map((item) => (
        <Card key={item.label}>
          <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
            <Stack spacing={0.5}>
              <Typography variant="overline" color="text.secondary">
                {item.label}
              </Typography>
              <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                {item.value}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {item.sub}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      ))}

      {/* 默认模型切换卡片 */}
      <Card>
        <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
          <Stack spacing={1.5}>
            <Typography variant="overline" color="text.secondary">
              默认模型
            </Typography>
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                variant="outlined"
                startIcon={<ReplayIcon />}
                onClick={onRefreshModels}
              >
                刷新模型
              </Button>
            </Stack>
            <Select
              size="small"
              value={selectValue}
              onChange={(e) => onModelChange(e.target.value)}
              sx={{ fontSize: "0.9rem" }}
            >
              {!selectableModels.length && (
                <MenuItem value="" disabled>
                  当前没有可用于小说任务流的在线模型
                </MenuItem>
              )}
              {selectableModels.map((m) => {
                const proto = protocolOverrides[m.id] || m.metadata?.protocol || "openai";
                return (
                  <MenuItem key={m.id} value={m.id}>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ width: "100%" }}>
                      <Stack spacing={0.25} sx={{ flex: 1 }}>
                        <Typography sx={{ fontSize: "0.875rem", fontWeight: 500 }}>
                          {m.display_name || m.id}
                        </Typography>
                        {m.provider && (
                          <Typography variant="caption" color="text.secondary">
                            {m.provider}
                          </Typography>
                        )}
                      </Stack>
                      <Chip
                        label={proto}
                        size="small"
                        color={proto === "anthropic" ? "info" : "default"}
                        variant="outlined"
                        sx={{ height: 20, fontSize: "0.7rem" }}
                      />
                    </Stack>
                  </MenuItem>
                );
              })}
            </Select>
            <Typography variant="caption" color="text.secondary">
              默认使用 Agent Team 当前默认模型；可在任务动作里临时覆盖。
            </Typography>
            <Typography variant="caption" color="text.secondary">
              可用小说模型 {selectableModels.length} 个
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {formatModelRefreshStatus(modelRefresh)}
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      {/* 协议设置卡片 */}
      <Card>
        <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
          <Stack spacing={1.5}>
            <Typography variant="overline" color="text.secondary">
              模型协议
            </Typography>
            {selectableModels.slice(0, 10).map((m) => {
              const proto = protocolOverrides[m.id] || m.metadata?.protocol || "openai";
              return (
                <Stack
                  key={m.id}
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  justifyContent="space-between"
                >
                  <Typography variant="body2" sx={{ fontSize: "0.8rem", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {m.display_name || m.id}
                  </Typography>
                  <Chip
                    label={proto}
                    size="small"
                    color={proto === "anthropic" ? "info" : "default"}
                    variant="outlined"
                    sx={{ height: 20, fontSize: "0.7rem", cursor: "pointer" }}
                    onClick={() => onToggleProtocol(m.id, proto)}
                  />
                </Stack>
              );
            })}
            {selectableModels.length > 10 && (
              <Typography variant="caption" color="text.secondary">
                ...还有 {selectableModels.length - 10} 个模型
              </Typography>
            )}
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}

// 骨架屏
function HomeSkeleton() {
  return (
    <Grid container spacing={3} sx={{ m: 0, width: "100%" }}>
      <Grid item xs={12} md={8}>
        <Card sx={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <Box sx={{ borderBottom: 1, borderColor: "divider", px: 2, py: 1 }}>
            <Skeleton variant="text" width={240} height={24} />
          </Box>
          <Box sx={{ p: 2, maxHeight: LIST_MAX_HEIGHT, overflow: "hidden" }}>
            <Stack spacing={1.5}>
              {[1, 2, 3].map((i) => (
                <Box key={i} sx={{ height: 80, bgcolor: "action.hover", borderRadius: 3 }} />
              ))}
            </Stack>
          </Box>
        </Card>
      </Grid>
      <Grid item xs={12} md={4}>
        <Stack spacing={2}>
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent sx={{ p: 2 }}>
                <Skeleton variant="text" width="60%" height={16} />
                <Skeleton variant="text" width="40%" height={28} sx={{ my: 0.5 }} />
                <Skeleton variant="text" width="70%" height={14} />
              </CardContent>
            </Card>
          ))}
        </Stack>
      </Grid>
    </Grid>
  );
}

export default function Home() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelRefresh, setModelRefresh] = useState<ModelRefreshState>({
    loading: false,
    error: "",
  });
  const [error, setError] = useState("");
  const [validationErrorHref, setValidationErrorHref] = useState<string | null>(null);
  const [modelUpdating, setModelUpdating] = useState(false);
  const [protocolOverrides, setProtocolOverrides] = useState<Record<string, string>>({});
  const [protocolUpdating, setProtocolUpdating] = useState(false);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMsg, setSnackbarMsg] = useState("");

  const showSnackbar = useCallback((msg: string) => {
    setSnackbarMsg(msg);
    setSnackbarOpen(true);
  }, []);

  const fetchDashboard = useCallback(() => {
    void getDashboard()
      .then((response) => {
        setDashboard(response);
        setError("");
        setValidationErrorHref(null);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "读取首页聚合数据失败");
      });
  }, []);

  const fetchModels = useCallback((refresh = false) => {
    setModelRefresh((current) => ({
      ...current,
      loading: true,
      error: "",
    }));
    void getModelCatalog({ refresh })
      .then((response) => {
        setModels(normalizeModelOptions(response.data ?? []));
        setModelRefresh((current) => ({
          ...current,
          loading: false,
          error: "",
          attemptedRefresh: current.attemptedRefresh || refresh,
          fetchedAt: response.meta?.fetched_at,
          cacheAgeSeconds: response.meta?.cache_age_seconds,
          cacheTtlSeconds: response.meta?.cache_ttl_seconds,
          cached: response.meta?.cached,
          invalidated: false,
          invalidatedModelLabel: undefined,
        }));
      })
      .catch((reason) => {
        setModelRefresh((current) => ({
          ...current,
          loading: false,
          error: reason instanceof Error ? reason.message : "读取模型列表失败",
        }));
      });
  }, []);

  const fetchProtocolSettings = useCallback(() => {
    void getProtocolSettings()
      .then((response) => {
        setProtocolOverrides(response.overrides || {});
      })
      .catch(() => {
        // 协议接口失败不影响主功能
      });
  }, []);

  useEffect(() => {
    fetchDashboard();
    fetchModels(false);
    fetchProtocolSettings();
  }, [fetchDashboard, fetchModels, fetchProtocolSettings]);

  const handleDeleteTask = useCallback((taskId: string) => {
    const task = dashboard?.continue_tasks.find((t) => t.task_id === taskId)
      ?? dashboard?.running_tasks.find((t) => t.task_id === taskId)
      ?? dashboard?.failed_tasks.find((t) => t.task_id === taskId)
      ?? dashboard?.completed_tasks?.find((t) => t.task_id === taskId);
    if (!task) return;
    const prompt = getDeletePrompt(task.status);
    if (!window.confirm(prompt)) return;
    void deleteTask(taskId)
      .then(() => {
        showSnackbar("任务已删除");
        fetchDashboard();
      })
      .catch((reason) => {
        showSnackbar(reason instanceof Error ? reason.message : "删除失败");
      });
  }, [dashboard, showSnackbar, fetchDashboard]);

  const handleModelChange = (modelId: string) => {
    if (modelUpdating) return;
    setModelUpdating(true);
    void updateDefaultModel(modelId)
      .then(() => {
        // 更新成功后刷新 dashboard 和模型列表
        setValidationErrorHref(null);
        fetchDashboard();
        fetchModels(false);
      })
      .catch((reason) => {
        const message = reason instanceof Error ? reason.message : "未知错误";
        setError(`切换模型失败：${message}`);
        setValidationErrorHref(getValidationLinkFromError(message, modelId));
      })
      .finally(() => setModelUpdating(false));
  };

  const handleToggleProtocol = useCallback((modelId: string, currentProtocol: string) => {
    if (protocolUpdating) return;
    const nextProtocol = currentProtocol === "openai" ? "anthropic" : "openai";
    setProtocolUpdating(true);
    void setModelProtocol(modelId, nextProtocol)
      .then(() => {
        setProtocolOverrides((prev) => ({ ...prev, [modelId]: nextProtocol }));
        showSnackbar(`${modelId} 协议已切换为 ${nextProtocol}`);
      })
      .catch((reason) => {
        showSnackbar(reason instanceof Error ? reason.message : "切换协议失败");
      })
      .finally(() => setProtocolUpdating(false));
  }, [protocolUpdating, showSnackbar]);

  return (
    <Container maxWidth="lg" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
      <Stack spacing={3} className="page-fade-in">
        {/* 紧凑标题栏 */}
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", sm: "center" }}
        >
          <Stack spacing={1} direction="row" alignItems="baseline" sx={{ flexWrap: "wrap", gap: 1 }}>
            <Typography
              variant="h4"
              sx={{ fontFamily: "var(--font-serif-sc)", lineHeight: 1.2 }}
            >
              小说工坊
            </Typography>
            <Chip label="LangChain + LangGraph + GPT-5.4" size="small" />
            <Typography variant="body2" color="text.secondary" sx={{ width: "100%" }}>
              从灵感到成稿，AI 辅助小说创作。输入创意，审核大纲，生成初稿。
            </Typography>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ flexShrink: 0 }}>
            <Button component={Link} href={newProjectHref()} size="large" variant="contained">
              创建任务
            </Button>
            <Button component={Link} href="/archive" size="large" variant="outlined">
              归档
            </Button>
          </Stack>
        </Stack>

        {error ? (
          <Alert
            severity="error"
            action={
              validationErrorHref ? (
                <Button component={Link} href={validationErrorHref} color="inherit" size="small">
                  去 AI 对话验证
                </Button>
              ) : undefined
            }
          >
            {error}
          </Alert>
        ) : null}

        {dashboard ? (
          <Grid container spacing={3} sx={{ m: 0, width: "100%" }}>
            {/* 主内容区 */}
            <Grid item xs={12} md={8}>
              <TaskTabPanel dashboard={dashboard} onDelete={handleDeleteTask} />
            </Grid>

            {/* 侧边栏 */}
            <Grid item xs={12} md={4}>
              <SidebarStats
                dashboard={dashboard}
                models={models}
                modelRefresh={modelRefresh}
                onModelChange={handleModelChange}
                onRefreshModels={() => fetchModels(true)}
                protocolOverrides={protocolOverrides}
                onToggleProtocol={handleToggleProtocol}
              />
            </Grid>
          </Grid>
        ) : (
          <HomeSkeleton />
        )}
      </Stack>
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={3000}
        onClose={() => setSnackbarOpen(false)}
        message={snackbarMsg}
      />
    </Container>
  );
}
