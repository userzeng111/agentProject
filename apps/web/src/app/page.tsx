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
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { Replay as ReplayIcon } from "@mui/icons-material";
import { getDashboard, getModelCatalog, normalizeModelOptions, updateDefaultModel } from "@/lib/api";
import { selectNovelTaskModels } from "@/lib/model-options.mjs";
import { formatTaskTypeLabel } from "@/lib/task-labels";
import { archiveDetailHref, resultHref, reviewHref, workspaceHref } from "@/lib/task-routes";
import { DashboardResponse, ModelListResponse, ModelOption, ModelRefreshState, TaskCardSummary, TaskStatus } from "@/lib/types";
import { formatModelRefreshStatus } from "@/features/task-models/model-refresh-state.mjs";

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

function resolveTaskHref(task: TaskCardSummary) {
  if (task.storage_state === "archive") {
    return archiveDetailHref(task.task_id);
  }
  if (
    task.status === "waiting_outline_review" ||
    task.status === "waiting_chapter_review" ||
    task.status === "waiting_verification_review"
  ) {
    return reviewHref(task.task_id);
  }
  if (task.status === "completed") {
    return resultHref(task.task_id);
  }
  return workspaceHref(task.task_id);
}

// 紧凑任务卡片
function TaskListItem({ task }: { task: TaskCardSummary }) {
  const isFailed = task.status === "failed";
  return (
    <Card
      variant="outlined"
      sx={{ borderRadius: 3, transition: "all 0.2s", "&:hover": { borderColor: "primary.main" } }}
    >
      <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
        <Stack spacing={1}>
          <Stack
            direction="row"
            spacing={1}
            justifyContent="space-between"
            alignItems="center"
          >
            <Typography
              variant="subtitle1"
              sx={{ fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            >
              {task.title || task.task_id}
            </Typography>
            <Chip
              label={statusLabelMap[task.status] ?? task.status}
              size="small"
              sx={{ flexShrink: 0 }}
            />
            <Button
              component={Link}
              href={resolveTaskHref(task)}
              size="small"
              sx={{ flexShrink: 0, minWidth: "auto", px: 1 }}
            >
              查看
            </Button>
            {isFailed && (
              <Button
                component={Link}
                href={`/create/?retry_from=${task.task_id}`}
                size="small"
                color="warning"
                startIcon={<ReplayIcon />}
                sx={{ flexShrink: 0, minWidth: "auto", px: 1 }}
              >
                重新创建
              </Button>
            )}
          </Stack>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {task.summary}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {task.current_stage}
            {" · "}
            {formatTaskTypeLabel({
              creativeMode: task.creative_mode,
              novelSize: task.novel_size,
              mode: task.mode,
            })}
            {" · "}
            {new Date(task.updated_at).toLocaleString()}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  );
}

// Tab 分组 + 独立滚动列表 + 固定分页器
const PAGE_SIZE = 5;
const LIST_MAX_HEIGHT = 480;

function TaskTabPanel({ dashboard }: { dashboard: DashboardResponse }) {
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

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue);
    setPage(1);
  };

  const emptyTexts = ["当前没有需要人工继续处理的任务。", "当前没有运行中的任务。", "当前没有失败任务。", "当前没有已完成的任务。"];

  return (
    <Card sx={{ borderRadius: 4, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* Tab 栏固定 */}
      <Box sx={{ borderBottom: 1, borderColor: "divider", flexShrink: 0 }}>
        <Tabs
          value={activeTab}
          onChange={handleTabChange}
          sx={{
            minHeight: 48,
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
              <TaskListItem key={task.task_id} task={task} />
            ))}
          </Stack>
        ) : (
          <Typography color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
            {emptyTexts[activeTab]}
          </Typography>
        )}
      </Box>

      {/* 分页器固定在底部 */}
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
    </Card>
  );
}

// 侧边栏 - 统计卡片
function SidebarStats({
  dashboard,
  models,
  modelMeta,
  modelRefresh,
  onModelChange,
  onRefreshModels,
}: {
  dashboard: DashboardResponse;
  models: ModelOption[];
  modelMeta: ModelListResponse["meta"] | null;
  modelRefresh: ModelRefreshState;
  onModelChange: (modelId: string) => void;
  onRefreshModels: () => void;
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
              {selectableModels.map((m) => (
                <MenuItem key={m.id} value={m.id}>
                  <Stack spacing={0.25}>
                    <Typography sx={{ fontSize: "0.875rem", fontWeight: 500 }}>
                      {m.display_name || m.id}
                    </Typography>
                    {m.provider && (
                      <Typography variant="caption" color="text.secondary">
                        {m.provider}
                      </Typography>
                    )}
                  </Stack>
                </MenuItem>
              ))}
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
    </Stack>
  );
}

// 骨架屏
function HomeSkeleton() {
  return (
    <Grid container spacing={3}>
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
  const [modelMeta, setModelMeta] = useState<ModelListResponse["meta"] | null>(null);
  const [modelRefresh, setModelRefresh] = useState<ModelRefreshState>({
    loading: false,
    error: "",
  });
  const [error, setError] = useState("");
  const [modelUpdating, setModelUpdating] = useState(false);

  const fetchDashboard = () => {
    void getDashboard()
      .then((response) => {
        setDashboard(response);
        setError("");
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "读取首页聚合数据失败");
      });
  };

  const fetchModels = useCallback((refresh = false) => {
    setModelRefresh((current) => ({
      ...current,
      loading: true,
      error: "",
    }));
    void getModelCatalog({ refresh })
      .then((response) => {
        setModels(normalizeModelOptions(response.data ?? []));
        setModelMeta(response.meta ?? null);
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

  useEffect(() => {
    fetchDashboard();
    fetchModels(false);
  }, [fetchModels]);

  const handleModelChange = (modelId: string) => {
    if (modelUpdating) return;
    setModelUpdating(true);
    void updateDefaultModel(modelId)
      .then(() => {
        // 更新成功后刷新 dashboard 和模型列表
        fetchDashboard();
        fetchModels(false);
      })
      .catch((reason) => {
        setError(`切换模型失败：${reason instanceof Error ? reason.message : "未知错误"}`);
      })
      .finally(() => setModelUpdating(false));
  };

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
            <Button component={Link} href="/create" size="large" variant="contained">
              创建任务
            </Button>
            <Button component={Link} href="/archive" size="large" variant="outlined">
              归档
            </Button>
          </Stack>
        </Stack>

        {error ? <Alert severity="error">{error}</Alert> : null}

        {dashboard ? (
          <Grid container spacing={3}>
            {/* 主内容区 */}
            <Grid item xs={12} md={8}>
              <TaskTabPanel dashboard={dashboard} />
            </Grid>

            {/* 侧边栏 */}
            <Grid item xs={12} md={4}>
              <SidebarStats
                dashboard={dashboard}
                models={models}
                modelMeta={modelMeta}
                modelRefresh={modelRefresh}
                onModelChange={handleModelChange}
                onRefreshModels={() => fetchModels(true)}
              />
            </Grid>
          </Grid>
        ) : (
          <HomeSkeleton />
        )}
      </Stack>
    </Container>
  );
}
