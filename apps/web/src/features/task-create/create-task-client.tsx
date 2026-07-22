"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Skeleton,
  Stack,
  Switch,
  TextField,
  Typography,
  alpha,
} from "@mui/material";
import {
  ArrowBack as ArrowBackIcon,
  ArrowForward as ArrowForwardIcon,
  CheckCircleOutline as CheckCircleOutlineIcon,
  CircleOutlined as CircleOutlinedIcon,
  ExpandMore as ExpandMoreIcon,
  NavigateNext as NavigateNextIcon,
} from "@mui/icons-material";
import { WorkbenchPageLayout } from "@/components/workbench-page-layout";
import { createTask, getModelCatalog, getRagSettings, getStyleProfiles, getTask, normalizeModelOptions, uploadAsset } from "@/lib/api";
import { isNovelTaskModelSupported, selectNovelTaskModels } from "@/lib/model-options.mjs";
import { formatModelRefreshStatus, isCurrentSelectionValid, resolveSelectionAfterRefresh } from "@/features/task-models/model-refresh-state.mjs";
import { settingsRagHref, workspaceHref } from "@/lib/task-routes";
import { formatCreativeModeLabel, formatNovelSizeLabel, needsStyleProfile, resolveCreativeMode, resolveNovelSize } from "@/lib/task-labels";
import { CreativeMode, ModelOption, ModelRefreshState, NovelSize, RagSettingsStatus, StyleProfile, TaskCreatePayload } from "@/lib/types";
import { getValidationLinkFromError } from "@/features/chat/model-validation-state.mjs";
import {
  CREATE_WORKBENCH_STAGES,
  resolveCreateWorkbenchReadiness,
  resolveCreateWorkbenchStages,
} from "./create-workbench-state.mjs";

const defaultPayload: TaskCreatePayload = {
  creative_mode: "original",
  novel_size: "short",
  target_chapter_count: 8,
  prompt: "",
  genre: "",
  style: "",
  style_profile_id: "",
  chapter_word_min: 1800,
  audience: "",
  banned: "",
  title_hint: "",
  model_id: "",
  auto_review: true,
  auto_review_model_mode: "follow_creative",
  review_model_id: "",
};

type TaskCreateModelSelection = Pick<
  TaskCreatePayload,
  "model_id" | "review_model_id" | "auto_review_model_mode"
>;

type CreateStepKey = "story" | "reference" | "execution";

/** 与 WorkbenchPageLayout 的 xl 工作台槽位保持一致，避免 1440px 起重复展示创建操作。 */
const CREATE_SUMMARY_MIN_WIDTH = 1440;

export function reconcileTaskCreateModelSelection(
  payload: TaskCreatePayload,
  selectableModels: ModelOption[],
): TaskCreatePayload;
export function reconcileTaskCreateModelSelection(
  payload: TaskCreateModelSelection,
  selectableModels: ModelOption[],
): TaskCreateModelSelection;
export function reconcileTaskCreateModelSelection(
  payload: TaskCreateModelSelection,
  selectableModels: ModelOption[],
): TaskCreateModelSelection {
  const nextSelection = resolveSelectionAfterRefresh({
    currentModelId: payload.model_id,
    availableModels: selectableModels,
  });
  const currentReviewModelId = typeof payload.review_model_id === "string" ? payload.review_model_id : "";
  const nextModelId = nextSelection.selectedModelId;

  return {
    ...payload,
    model_id: nextModelId,
    review_model_id:
      payload.auto_review_model_mode === "follow_creative"
        ? nextModelId
        : isCurrentSelectionValid(currentReviewModelId, selectableModels)
          ? currentReviewModelId
          : "",
  };
}

const creativeModeOptions: { value: CreativeMode; label: string }[] = [
  { value: "original", label: "全新原创" },
  { value: "fanfic", label: "同人创作" },
  { value: "style_remix", label: "风格复刻" },
];

const novelSizeOptions: { value: NovelSize; label: string }[] = [
  { value: "short", label: "短篇（8-80章）" },
  { value: "medium", label: "中篇（80-400章）" },
  { value: "long", label: "长篇（400章以上）" },
];

function formatTokenCount(value?: number) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "未声明";
  }
  return `${value.toLocaleString()} tokens`;
}

function formatCacheLabel(model?: ModelOption) {
  const cache = model?.capabilities?.cache;
  if (!cache) {
    return "缓存：未声明";
  }
  if (cache.runtime_context_cache) {
    return "缓存：支持运行时上下文缓存";
  }
  if (cache.prompt_cache || cache.response_cache) {
    return "缓存：支持部分缓存能力";
  }
  return "缓存：未启用";
}

function formatCompressionLabel(model?: ModelOption) {
  const compression = model?.capabilities?.compression;
  if (!compression) {
    return "压缩：未声明";
  }
  if (compression.supported) {
    return `压缩：支持${compression.strategy ? ` ${compression.strategy}` : ""}`.trim();
  }
  if (compression.may_compress) {
    return `压缩：可能按需启用${compression.strategy ? `（${compression.strategy}）` : ""}`;
  }
  return "压缩：未启用";
}

function formatStyleProfileSummary(profile: StyleProfile) {
  const parts = [
    profile.source_novel ? `《${profile.source_novel}》` : "",
    profile.source_author ? `作者：${profile.source_author}` : "",
    profile.genre ? `题材：${profile.genre}` : "",
  ].filter(Boolean);
  return parts.length ? `${profile.name} · ${parts.join(" · ")}` : profile.name;
}

function formatStyleProfileHelper(profile?: StyleProfile) {
  if (!profile) {
    return "当前模式下尚未选择风格实例。";
  }
  const parts = [
    profile.source_novel ? `原作《${profile.source_novel}》` : "",
    profile.source_author ? `作者 ${profile.source_author}` : "",
    profile.genre ? `题材 ${profile.genre}` : "",
    typeof profile.fidelity_score === "number" ? `保真度 ${profile.fidelity_score}` : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

export default function CreateTaskClient() {
  const router = useRouter();
  const [payload, setPayload] = useState(defaultPayload);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelRefresh, setModelRefresh] = useState<ModelRefreshState>({ loading: false, error: "" });
  const [styleProfiles, setStyleProfiles] = useState<StyleProfile[]>([]);
  const [styleProfilesLoading, setStyleProfilesLoading] = useState(true);
  const [styleProfilesError, setStyleProfilesError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [retryLoaded, setRetryLoaded] = useState(false);
  const [retryPrefillNotice, setRetryPrefillNotice] = useState("");
  const [ragStatus, setRagStatus] = useState<RagSettingsStatus | null>(null);
  const [activeStep, setActiveStep] = useState<CreateStepKey>("story");
  const [resetConfirmationOpen, setResetConfirmationOpen] = useState(false);
  const [submissionPhase, setSubmissionPhase] = useState<"" | "creating" | "uploading">("");
  const [createdTaskAfterUploadFailure, setCreatedTaskAfterUploadFailure] = useState("");
  const currentModelIdRef = useRef(payload.model_id);
  const currentModelsRef = useRef<ModelOption[]>([]);

  useEffect(() => {
    currentModelIdRef.current = payload.model_id;
  }, [payload.model_id]);

  useEffect(() => {
    currentModelsRef.current = models;
  }, [models]);

  const loadModels = useCallback(async (refresh = false) => {
    try {
      setModelsLoading(true);
      setModelRefresh((current) => ({ ...current, loading: true, error: "" }));
      const response = await getModelCatalog({ refresh });
      const nextModels = normalizeModelOptions(response.data ?? []);
      const selectableModelOptions = selectNovelTaskModels(nextModels);
      const previousModelId = typeof currentModelIdRef.current === "string" ? currentModelIdRef.current.trim() : "";
      const nextSelection = resolveSelectionAfterRefresh({
        currentModelId: previousModelId,
        availableModels: selectableModelOptions,
      });
      setModels(nextModels);
      setModelRefresh((current) => ({
        ...current,
        loading: false,
        error: "",
        attemptedRefresh: current.attemptedRefresh || refresh,
        fetchedAt: response.meta?.fetched_at,
        cacheAgeSeconds: response.meta?.cache_age_seconds,
        cacheTtlSeconds: response.meta?.cache_ttl_seconds,
        cached: response.meta?.cached,
        invalidated: refresh && nextSelection.invalidated,
        invalidatedModelLabel:
          refresh && nextSelection.invalidated
            ? currentModelsRef.current.find((option) => option.id === previousModelId)?.display_name || previousModelId || undefined
            : undefined,
      }));
      setPayload((current) => reconcileTaskCreateModelSelection(current, selectableModelOptions));
    } catch (loadError) {
      const nextError = loadError instanceof Error ? loadError.message : "读取模型列表失败";
      setError(nextError);
      setModels([]);
      setPayload((current) => reconcileTaskCreateModelSelection(current, []));
      setModelRefresh((current) => ({
        ...current,
        loading: false,
        error: nextError,
      }));
    } finally {
      setModelsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadModels(false);
  }, [loadModels]);

  useEffect(() => {
    async function loadStyleProfiles() {
      try {
        setStyleProfilesLoading(true);
        setStyleProfilesError("");
        setStyleProfiles(await getStyleProfiles());
      } catch (loadError) {
        setStyleProfiles([]);
        setStyleProfilesError(loadError instanceof Error ? loadError.message : "读取风格实例列表失败");
      } finally {
        setStyleProfilesLoading(false);
      }
    }

    void loadStyleProfiles();
  }, []);

  useEffect(() => {
    async function loadRagStatus() {
      try {
        setRagStatus(await getRagSettings());
      } catch {
        setRagStatus({
          available: false,
          library_dir: "",
          faiss_index_path: "",
          sqlite_path: "",
          sources: [],
          last_result: null,
        });
      }
    }
    void loadRagStatus();
  }, []);

  // 检查 URL 中是否有 retry_from 参数，加载原始任务数据预填充表单
  useEffect(() => {
    if (retryLoaded) return;
    const params = new URLSearchParams(window.location.search);
    const retryFrom = params.get("retry_from");
    if (!retryFrom) {
      setRetryLoaded(true);
      return;
    }

    async function loadRetryTask() {
      try {
        const task = await getTask(retryFrom!);
        const input = task.input;
        setPayload((current) => ({
          ...current,
          prompt: input.prompt ?? current.prompt,
          creative_mode: input.creative_mode ?? task.creative_mode ?? resolveCreativeMode(undefined, task.mode),
          novel_size: input.novel_size ?? task.novel_size ?? resolveNovelSize(undefined, task.mode),
          target_chapter_count: input.target_chapter_count ?? task.target_chapter_count ?? current.target_chapter_count,
          genre: input.genre ?? current.genre,
          style: input.style ?? current.style,
          chapter_word_min: input.chapter_word_min ?? input.target_words ?? task.chapter_word_min ?? current.chapter_word_min,
          audience: input.audience ?? current.audience,
          banned: input.banned ?? current.banned,
          title_hint: input.title_hint ?? current.title_hint,
          model_id: input.model_id ?? task.creative_model_id ?? task.model_id ?? current.model_id,
          auto_review_model_mode: input.auto_review_model_mode ?? task.auto_review_model_mode ?? current.auto_review_model_mode,
          review_model_id: input.review_model_id ?? task.review_model_id ?? current.review_model_id,
          style_profile_id: input.style_profile_id ?? current.style_profile_id,
        }));
        setRetryPrefillNotice("已从原任务预填创作设定，你可以继续编辑后重新创建。");
      } catch (loadError) {
        // 重试数据加载失败不影响正常创建流程
        console.warn("加载重试任务数据失败：", loadError);
      } finally {
        setRetryLoaded(true);
      }
    }

    void loadRetryTask();
  }, [retryLoaded]);

  const selectedModel = useMemo(
    () => models.find((item) => item.id === payload.model_id),
    [models, payload.model_id],
  );
  const selectedReviewModel = useMemo(
    () => models.find((item) => item.id === payload.review_model_id),
    [models, payload.review_model_id],
  );
  const selectableModels = useMemo(
    () => models.filter((item) => isNovelTaskModelSupported(item)),
    [models],
  );
  const resetPayload = useMemo(
    () => ({
      ...defaultPayload,
    }),
    [],
  );
  const hasValidSelectedModel = isCurrentSelectionValid(payload.model_id, selectableModels);
  const hasValidReviewModel =
    !payload.auto_review ||
    payload.auto_review_model_mode !== "fixed" ||
    isCurrentSelectionValid(payload.review_model_id, selectableModels);
  const validationErrorHref = getValidationLinkFromError(
    error,
    error.includes("固定审核") ? payload.review_model_id : payload.model_id,
  );

  const selectedModelCapabilities = selectedModel?.capabilities;
  const selectedStyleProfile = useMemo(
    () => styleProfiles.find((item) => item.id === payload.style_profile_id) ?? null,
    [payload.style_profile_id, styleProfiles],
  );
  const currentCreativeMode = payload.creative_mode;
  const requiresStyleProfile = needsStyleProfile(currentCreativeMode);
  const chapterCountRangeText = useMemo(() => {
    const target = Number(payload.target_chapter_count || 0);
    if (!Number.isFinite(target) || target <= 0) {
      return "请输入目标总章节数";
    }
    const lower = Math.max(1, Math.floor(target * 0.9));
    const upper = Math.max(lower, Math.ceil(target * 1.1));
    return `${lower}-${upper}`;
  }, [payload.target_chapter_count]);
  const workbenchStateOptions = {
    payload,
    ragAvailable: ragStatus?.available === true,
    hasValidCreativeModel: Boolean(hasValidSelectedModel && selectedModel && isNovelTaskModelSupported(selectedModel)),
    hasValidReviewModel,
    hasStyleProfile: Boolean(selectedStyleProfile),
  };
  const readiness = resolveCreateWorkbenchReadiness(workbenchStateOptions);
  const createSteps = resolveCreateWorkbenchStages(workbenchStateOptions);
  const firstIncomplete = readiness.firstIncomplete;
  const canSubmit = firstIncomplete === null;
  const isRagUnavailable = ragStatus?.available === false;
  const readinessMessage =
    firstIncomplete?.incompleteHint || "关键设定已完成，可以创建任务。";
  const modelFeatures = useMemo(
    () =>
      Array.isArray(selectedModelCapabilities?.features)
        ? selectedModelCapabilities.features.slice(0, 6)
        : [],
    [selectedModelCapabilities],
  );

  useEffect(() => {
    if (!requiresStyleProfile) {
      return;
    }
    setPayload((current) => {
      if (!needsStyleProfile(current.creative_mode) || current.style_profile_id || !styleProfiles.length) {
        return current;
      }
      return {
        ...current,
        style_profile_id: styleProfiles[0].id,
      };
    });
  }, [requiresStyleProfile, styleProfiles]);

  const updateField =
    (field: keyof TaskCreatePayload) =>
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const value =
        field === "chapter_word_min" || field === "target_chapter_count"
          ? Number(event.target.value)
          : event.target.value;
      if (field === "model_id") {
        setModelRefresh((current) => ({ ...current, invalidated: false, invalidatedModelLabel: undefined }));
      }
      setError("");
      setPayload((current) => {
        const nextPayload = { ...current, [field]: value };
        if (field === "model_id" && current.auto_review_model_mode === "follow_creative") {
          nextPayload.review_model_id = String(value);
        }
        if (field === "auto_review_model_mode" && value === "follow_creative") {
          nextPayload.review_model_id = current.model_id || "";
        }
        return nextPayload;
      });
    };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const focusStepField = (step: CreateStepKey, targetId?: string) => {
    setActiveStep(step);
    if (!targetId) {
      return;
    }
    window.requestAnimationFrame(() => {
      document.getElementById(targetId)?.focus();
    });
  };

  const goToReadinessItem = (item: typeof readiness.items[number]) => {
    const targetIds: Record<string, string> = {
      prompt: "create-prompt",
      "creative-model": "create-model",
      chapters: "create-chapter-count",
      rag: "create-rag-status",
      "style-profile": "create-style-profile",
      "review-model": "create-review-model",
    };
    focusStepField(item.stage as CreateStepKey, targetIds[item.key]);
  };

  const confirmReset = () => {
    setPayload(resetPayload);
    setFile(null);
    setError("");
    setCreatedTaskAfterUploadFailure("");
    setActiveStep("story");
    setResetConfirmationOpen(false);
  };

  const handleSubmit = async () => {
    if (!ragStatus?.available) {
      setError("当前小说知识库尚未构建，请先前往设置页完成索引同步。");
      return;
    }
    if (!selectedModel || !isNovelTaskModelSupported(selectedModel)) {
      setError("当前所选模型未完成小说工作流兼容性验证，请改用已验证模型。");
      return;
    }
    if (
      payload.auto_review &&
      payload.auto_review_model_mode === "fixed" &&
      (!selectedReviewModel || !isNovelTaskModelSupported(selectedReviewModel))
    ) {
      setError("当前固定审核模型未完成小说工作流兼容性验证，请改用已验证模型或切换为跟随任务创作模型。");
      return;
    }
    if (requiresStyleProfile && !selectedStyleProfile) {
      setError(`请先选择一个有效的${formatCreativeModeLabel(currentCreativeMode)}参考实例。`);
      return;
    }
    let createdTaskId = "";
    try {
      setSubmitting(true);
      setSubmissionPhase("creating");
      setError("");
      setCreatedTaskAfterUploadFailure("");
      const task = await createTask({
        ...payload,
        creative_model_id: payload.model_id,
        review_model_id:
          payload.auto_review && payload.auto_review_model_mode === "fixed"
            ? payload.review_model_id
            : payload.model_id,
      });
      createdTaskId = task.id;
      if (file) {
        setSubmissionPhase("uploading");
        await uploadAsset(task.id, file);
      }
      router.push(workspaceHref(task.id));
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "创建任务失败";
      if (createdTaskId) {
        setCreatedTaskAfterUploadFailure(createdTaskId);
        setError(`任务已经创建，但参考文本上传失败：${message}`);
      } else {
        setError(message);
      }
    } finally {
      setSubmitting(false);
      setSubmissionPhase("");
    }
  };

  const nextStep = CREATE_WORKBENCH_STAGES[
    Math.min(CREATE_WORKBENCH_STAGES.findIndex((step) => step.key === activeStep) + 1, CREATE_WORKBENCH_STAGES.length - 1)
  ]?.key as CreateStepKey;
  const previousStep = CREATE_WORKBENCH_STAGES[
    Math.max(CREATE_WORKBENCH_STAGES.findIndex((step) => step.key === activeStep) - 1, 0)
  ]?.key as CreateStepKey;
  const isFirstStep = activeStep === "story";
  const isLastStep = activeStep === "execution";
  const submissionLabel =
    submissionPhase === "uploading" ? "正在上传参考文本..." : submissionPhase === "creating" ? "正在创建任务..." : "创建并进入任务页";

  const renderCreateAction = (fullWidth = true) => {
    if (isRagUnavailable) {
      return (
        <Button component={Link} href={settingsRagHref()} variant="contained" fullWidth={fullWidth}>
          前往知识库同步
        </Button>
      );
    }
    return (
      <Button
        disabled={submitting || !canSubmit}
        onClick={handleSubmit}
        variant="contained"
        fullWidth={fullWidth}
        className="btn-soft-hover"
      >
        {submissionLabel}
      </Button>
    );
  };

  return (
    <WorkbenchPageLayout
      testId="task-create-workbench"
      contentLabel="创建任务表单"
      responsiveSlots={{ navigation: "md", aside: "xl" }}
      navigation={
        <Stack spacing={2}>
          <Box>
            <Typography variant="overline" color="text.secondary">
              创作工作台
            </Typography>
            <Typography variant="body2" color="text.secondary">
              每一步都可返回修改，已填写内容会保留。
            </Typography>
          </Box>
          <Stack component="nav" aria-label="创建任务步骤" spacing={0.75}>
            {createSteps.map((step, index) => {
              const isActive = step.key === activeStep;
              return (
              <Button
                key={step.key}
                data-testid={`create-step-${step.key}`}
                aria-current={isActive ? "step" : undefined}
                onClick={() => focusStepField(step.key as CreateStepKey)}
                variant="text"
                color="inherit"
                sx={{
                  minHeight: 44,
                  justifyContent: "flex-start",
                  gap: 1.25,
                  px: 1,
                  borderRadius: 1.5,
                  color: isActive ? "primary.main" : "text.primary",
                  bgcolor: isActive ? (theme) => alpha(theme.palette.primary.main, 0.1) : "transparent",
                  "&:hover": { bgcolor: (theme) => alpha(theme.palette.primary.main, 0.08) },
                }}
              >
                <Box
                  component="span"
                  sx={{
                    display: "inline-flex",
                    color: step.complete ? "success.main" : isActive ? "primary.main" : "text.secondary",
                  }}
                >
                  {step.complete ? <CheckCircleOutlineIcon fontSize="small" /> : <CircleOutlinedIcon fontSize="small" />}
                </Box>
                <Stack alignItems="flex-start" spacing={0.1} sx={{ minWidth: 0 }}>
                  <Typography variant="body2" fontWeight={isActive ? 700 : 500}>
                    {index + 1}. {step.label}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {isActive ? "正在编辑" : step.complete ? "已完成" : "待补充"}
                  </Typography>
                </Stack>
              </Button>
              );
            })}
          </Stack>
          <Divider />
          <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.7 }}>
            准备度会持续提示仍缺少的创作设定，点击缺项可直接返回对应步骤。
          </Typography>
        </Stack>
      }
      header={
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            gap: 1,
            minWidth: 0,
            px: { xs: 1.5, sm: 2.5, lg: 3 },
            pt: { xs: 1.5, sm: 2.5 },
            pb: { xs: 1.25, sm: 2 },
            borderBottom: "1px solid",
            borderColor: "divider",
          }}
        >
          <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
            <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
              <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
                首页
              </Typography>
            </Link>
            <Typography variant="body2">创建任务</Typography>
          </Breadcrumbs>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1}
            justifyContent="space-between"
            alignItems={{ xs: "flex-start", sm: "center" }}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="h4" component="h1" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                创建小说任务
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                先写下故事核心，再补充参考与执行设定。
              </Typography>
            </Box>
          </Stack>
          <Stack
            component="nav"
            aria-label="移动端创建步骤"
            direction="row"
            spacing={0.5}
            sx={{ display: { xs: "flex", md: "none" }, overflowX: "auto", pb: 0.25 }}
          >
            {createSteps.map((step, index) => {
              const isActive = step.key === activeStep;
              return (
                <Button
                  key={step.key}
                  aria-current={isActive ? "step" : undefined}
                  onClick={() => focusStepField(step.key as CreateStepKey)}
                  variant={isActive ? "contained" : "outlined"}
                  size="small"
                  sx={{ minHeight: 36, flex: "1 0 auto" }}
                >
                  {index + 1}. {step.label}
                </Button>
              );
            })}
          </Stack>
          <Typography role="status" variant="caption" color={canSubmit ? "success.main" : "text.secondary"}>
            {readinessMessage}
          </Typography>
        </Box>
      }
      aside={
        <Stack spacing={2} data-testid="create-desktop-summary">
          <Box>
            <Typography variant="subtitle1" fontWeight={700}>
              创建准备度
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              完成所有必填项后即可开始生成大纲。
            </Typography>
          </Box>
          <Stack spacing={0.5}>
            {readiness.items.map((item) => (
              <Button
                key={item.key}
                onClick={() => goToReadinessItem(item)}
                color={item.complete ? "success" : "inherit"}
                variant="text"
                sx={{ justifyContent: "flex-start", minHeight: 40, px: 0.5 }}
              >
                {item.complete ? <CheckCircleOutlineIcon fontSize="small" /> : <CircleOutlinedIcon fontSize="small" />}
                <Typography component="span" variant="body2" sx={{ ml: 1, textAlign: "left" }}>
                  {item.complete ? item.label : item.incompleteHint}
                </Typography>
              </Button>
            ))}
          </Stack>
          <Divider />
          <Stack spacing={1}>
            <Typography variant="caption" color="text.secondary">
              {formatNovelSizeLabel(payload.novel_size)} · {payload.target_chapter_count || "未填写"} 章
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
              {selectedModel?.display_name || selectedModel?.id || "尚未选择创作模型"}
            </Typography>
            {renderCreateAction()}
          </Stack>
          <Button onClick={() => setResetConfirmationOpen(true)} variant="text" fullWidth>
            重置表单
          </Button>
        </Stack>
      }
      footer={
        <Box
          data-testid="create-mobile-action"
          sx={{
            display: "block",
            [`@media (min-width: ${CREATE_SUMMARY_MIN_WIDTH}px)`]: { display: "none" },
            borderTop: 1,
            borderColor: "divider",
            bgcolor: "background.paper",
            p: 1.5,
          }}
        >
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <Typography role="status" variant="caption" color={canSubmit ? "success.main" : "text.secondary"} sx={{ flex: 1 }}>
              {canSubmit ? "关键设定已完成，可以开始创作。" : `还需完成：${readinessMessage}`}
            </Typography>
            <Box sx={{ minWidth: { sm: 208 } }}>{renderCreateAction()}</Box>
            <Button size="small" onClick={() => setResetConfirmationOpen(true)}>
              重置表单
            </Button>
          </Stack>
        </Box>
      }
    >
      <Stack spacing={2.5} className="page-fade-in" sx={{ minWidth: 0 }}>

      {ragStatus?.available === false ? (
        <Alert
          severity="warning"
          sx={{ flexShrink: 0 }}
          action={
            <Button component={Link} href={settingsRagHref()} color="inherit" size="small">
              查看 RAG 设置
            </Button>
          }
        >
          当前小说知识库未构建，请先前往设置页完成索引同步，再开始创作。
        </Alert>
      ) : null}

      {error ? (
        <Alert
          severity="error"
          role="alert"
          sx={{ flexShrink: 0 }}
          action={
            createdTaskAfterUploadFailure ? (
              <Button component={Link} href={workspaceHref(createdTaskAfterUploadFailure)} color="inherit" size="small">
                打开已创建任务
              </Button>
            ) : validationErrorHref ? (
              <Button component={Link} href={validationErrorHref} color="inherit" size="small">
                去 AI 对话验证
              </Button>
            ) : undefined
          }
        >
          {error}
        </Alert>
      ) : null}

      {retryPrefillNotice ? <Alert severity="info">{retryPrefillNotice}</Alert> : null}

      <Box
        data-testid="create-readiness"
        sx={(theme) => ({
          display: "block",
          [`@media (min-width: ${CREATE_SUMMARY_MIN_WIDTH}px)`]: { display: "none" },
          p: 1.25,
          borderRadius: 1.5,
          border: "1px solid",
          borderColor: "divider",
          bgcolor: alpha(theme.palette.primary.main, 0.035),
        })}
      >
        <Stack spacing={0.5}>
          <Typography variant="subtitle2">创建准备度</Typography>
          {readiness.items.filter((item) => !item.complete).length ? (
            readiness.items.filter((item) => !item.complete).map((item) => (
              <Button
                key={item.key}
                onClick={() => goToReadinessItem(item)}
                variant="text"
                color="inherit"
                sx={{ justifyContent: "flex-start", minHeight: 36, px: 0.5 }}
              >
                <CircleOutlinedIcon fontSize="small" />
                <Typography component="span" variant="body2" sx={{ ml: 1 }}>
                  {item.incompleteHint}
                </Typography>
              </Button>
            ))
          ) : (
            <Stack direction="row" spacing={1} alignItems="center">
              <CheckCircleOutlineIcon color="success" fontSize="small" />
              <Typography variant="body2" color="success.main">关键设定已完成。</Typography>
            </Stack>
          )}
        </Stack>
      </Box>

      <Stack spacing={2.5}>
        {activeStep === "story" ? <Card
          component="section"
          id="create-story"
          className="card-lift"
          sx={{ p: 0, scrollMarginTop: 16, "& .MuiCardContent-root": { p: { xs: 2, sm: 3 } } }}
        >
          <CardContent>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h6" component="h2">故事核心</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                从一句清晰的故事设想开始，再确定创作方式与规模。
              </Typography>
            </Box>
            <TextField
              id="create-prompt"
              label="创意提示词"
              value={payload.prompt}
              onChange={updateField("prompt")}
              multiline
              minRows={5}
              required
              placeholder="例如：写一个带有潮湿海港气味的悬疑故事，主角是负责夜航记录的女学者。"
            />
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" },
                gap: 2,
              }}
            >
              <TextField
                select
                label="创作类型"
                value={payload.creative_mode}
                onChange={updateField("creative_mode")}
              >
                {creativeModeOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField label="题材" value={payload.genre} onChange={updateField("genre")} />
              <TextField label="标题倾向" value={payload.title_hint} onChange={updateField("title_hint")} />
              <TextField label="目标读者" value={payload.audience} onChange={updateField("audience")} />
            </Box>
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>篇幅与章节</Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" },
                  gap: 2,
                }}
              >
              <TextField
                select
                label="篇幅规模"
                value={payload.novel_size}
                onChange={updateField("novel_size")}
                helperText={`当前：${formatNovelSizeLabel(payload.novel_size)}，仅作为规模标签，章节总量以下方手填值为准。`}
              >
                {novelSizeOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                id="create-chapter-count"
                label="目标总章节数"
                type="number"
                value={payload.target_chapter_count ?? ""}
                onChange={updateField("target_chapter_count")}
                inputProps={{ min: 1, step: 1 }}
                helperText={`允许浮动范围：${chapterCountRangeText}`}
              />
              </Box>
            </Box>

            {modelsLoading ? (
              <Skeleton variant="rounded" height={56} />
            ) : (
              <Stack spacing={1.5}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                  <Typography variant="subtitle2">任务创作模型</Typography>
                  <Button size="small" variant="outlined" disabled={modelsLoading || modelRefresh.loading} onClick={() => void loadModels(true)}>
                    {modelRefresh.loading ? "刷新中..." : "刷新模型"}
                  </Button>
                </Stack>
                <TextField
                  id="create-model"
                  select
                  label="任务创作模型"
                  inputProps={{ "data-testid": "model-select" }}
                  value={hasValidSelectedModel ? payload.model_id : ""}
                  onChange={updateField("model_id")}
                  helperText={
                    !models.length
                      ? "当前后端没有返回可用模型"
                      : !selectableModels.length
                        ? "当前没有通过小说工作流兼容性验证的模型"
                        : payload.model_id && !hasValidSelectedModel
                          ? "当前已选模型不可用，请手动重新选择兼容模型。"
                          : selectedModel && !isNovelTaskModelSupported(selectedModel)
                        ? "当前模型未完成小说工作流兼容性验证，请改用已验证模型。"
                        : "模型选项来自后端 /api/models 接口。"
                  }
                >
                  <MenuItem value="">
                    <em>请选择任务创作模型</em>
                  </MenuItem>
                  {models.length ? (
                    models.map((option) => (
                      <MenuItem key={option.id} value={option.id} disabled={!isNovelTaskModelSupported(option)}>
                        {(option.display_name || option.id) + (!isNovelTaskModelSupported(option) ? "（未验证）" : "")}
                      </MenuItem>
                    ))
                  ) : (
                    <MenuItem value="" disabled>
                      暂无可用模型
                    </MenuItem>
                  )}
                </TextField>
                <Typography variant="caption" color="text.secondary">
                  {formatModelRefreshStatus(modelRefresh)}
                </Typography>
                {!hasValidSelectedModel ? (
                  <Alert severity="warning">当前已选模型已失效或尚未选择，请手动重选后再创建任务。</Alert>
                ) : null}
              </Stack>
            )}

            {!modelsLoading && selectedModel && (
              <Accordion disableGutters variant="outlined" sx={{ borderRadius: "8px !important", overflow: "hidden" }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography variant="subtitle2">查看模型能力详情</Typography>
                    {selectedModel.metadata?.compatibility ? (
                      <Chip
                        size="small"
                        color={isNovelTaskModelSupported(selectedModel) ? "success" : "warning"}
                        label={isNovelTaskModelSupported(selectedModel) ? "小说任务：已验证" : "小说任务：未验证"}
                      />
                    ) : null}
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`上下文：${formatTokenCount(
                        selectedModelCapabilities?.context_window?.max_input_tokens ||
                          selectedModelCapabilities?.context_window?.max_total_tokens,
                      )}`}
                    />
                  </Stack>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                <Box
                  sx={(theme) => ({
                    p: 1.5,
                    borderRadius: 1.5,
                    bgcolor: alpha(theme.palette.text.primary, 0.03),
                  })}
                >
                <Stack spacing={1.5}>
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    spacing={1}
                    justifyContent="space-between"
                    alignItems={{ xs: "flex-start", sm: "center" }}
                  >
                    <Box>
                      <Typography variant="subtitle1">模型能力摘要</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {selectedModel.display_name || selectedModel.id}
                        {selectedModel.provider ? ` · ${selectedModel.provider}` : ""}
                      </Typography>
                    </Box>
                    {selectedModel.metadata?.source && (
                      <Chip size="small" variant="outlined" label={`来源：${selectedModel.metadata.source}`} />
                    )}
                    {selectedModel.metadata?.compatibility && (
                      <Chip
                        size="small"
                        variant="outlined"
                        color={isNovelTaskModelSupported(selectedModel) ? "success" : "warning"}
                        label={isNovelTaskModelSupported(selectedModel) ? "小说任务：已验证" : "小说任务：未验证"}
                      />
                    )}
                  </Stack>

                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`上下文窗口：${formatTokenCount(
                        selectedModelCapabilities?.context_window?.max_input_tokens ||
                          selectedModelCapabilities?.context_window?.max_total_tokens,
                      )}`}
                    />
                    <Chip size="small" variant="outlined" label={formatCacheLabel(selectedModel)} />
                    <Chip size="small" variant="outlined" label={formatCompressionLabel(selectedModel)} />
                  </Stack>

                  <Typography variant="body2" color="text.secondary">
                    输入上限：{formatTokenCount(selectedModelCapabilities?.context_window?.max_input_tokens)}
                    {" · "}
                    输出上限：{formatTokenCount(selectedModelCapabilities?.context_window?.max_output_tokens)}
                    {" · "}
                    推荐输入预算：{formatTokenCount(selectedModelCapabilities?.context_window?.recommended_input_tokens)}
                  </Typography>

                  {modelFeatures.length ? (
                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {modelFeatures.map((feature) => (
                        <Chip key={feature} size="small" label={feature} />
                      ))}
                    </Stack>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      后端暂未返回更多能力画像，创建流程仍保持兼容。
                    </Typography>
                  )}
                </Stack>
                </Box>
                </AccordionDetails>
              </Accordion>
            )}

          </Stack>
        </CardContent>
      </Card> : null}

      {activeStep === "reference" ? <Card
        component="section"
        id="create-reference"
        className="card-lift"
        sx={{ p: 0, scrollMarginTop: 16, "& .MuiCardContent-root": { p: { xs: 2, sm: 3 } } }}
      >
        <CardContent>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h6" component="h2">参考与边界</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                为故事补充参考来源、文风倾向与明确的创作边界。
              </Typography>
            </Box>

            {requiresStyleProfile ? (
              <Box
                sx={(theme) => ({
                  p: 2,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  backgroundColor: alpha(theme.palette.primary.main, 0.03),
                })}
              >
                <Stack spacing={2}>
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    spacing={1}
                    justifyContent="space-between"
                    alignItems={{ xs: "flex-start", sm: "center" }}
                  >
                    <Box>
                      <Typography variant="subtitle1">参考实例</Typography>
                      <Typography variant="body2" color="text.secondary">
                        从后端 `GET /api/style-profiles` 拉取实例列表。
                        {currentCreativeMode === "fanfic"
                          ? "同人创作会把实例当作世界观与角色连续性约束。"
                          : "风格复刻会把实例当作文风与叙事方式基础。"}
                      </Typography>
                    </Box>
                    {selectedStyleProfile && (
                      <Chip size="small" variant="outlined" label={`已选：${selectedStyleProfile.name}`} />
                    )}
                  </Stack>

                  {styleProfilesLoading ? (
                    <Skeleton variant="rounded" height={56} />
                  ) : (
                    <TextField
                      id="create-style-profile"
                      select
                      label={currentCreativeMode === "fanfic" ? "同人参考实例" : "风格参考实例"}
                      value={payload.style_profile_id}
                      onChange={updateField("style_profile_id")}
                      helperText={
                        styleProfilesError
                          ? styleProfilesError
                          : styleProfiles.length
                            ? "选择一个实例，再用下方文本补充额外创作要求。"
                            : "当前没有可用实例。"
                      }
                      error={Boolean(styleProfilesError)}
                      disabled={Boolean(styleProfilesError) && !styleProfiles.length}
                    >
                      {styleProfiles.length ? (
                        styleProfiles.map((profile) => (
                          <MenuItem key={profile.id} value={profile.id}>
                            <Stack spacing={0.25} sx={{ py: 0.5 }}>
                              <Typography variant="body2">{profile.name}</Typography>
                              <Typography variant="caption" color="text.secondary">
                                {formatStyleProfileSummary(profile)}
                              </Typography>
                            </Stack>
                          </MenuItem>
                        ))
                      ) : (
                        <MenuItem value="" disabled>
                          暂无可用实例
                        </MenuItem>
                      )}
                    </TextField>
                  )}

                  {selectedStyleProfile ? (
                    <Box
                      sx={(theme) => ({
                        p: 2,
                        borderRadius: 2,
                        border: "1px solid",
                        borderColor: "divider",
                        backgroundColor: alpha(theme.palette.text.primary, 0.02),
                      })}
                    >
                      <Stack spacing={1.25}>
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Typography variant="subtitle2">{selectedStyleProfile.name}</Typography>
                          <Chip size="small" label={`保真度 ${selectedStyleProfile.fidelity_score}`} />
                        </Stack>
                        <Typography variant="body2" color="text.secondary">
                          {formatStyleProfileHelper(selectedStyleProfile)}
                        </Typography>
                        {selectedStyleProfile.description ? (
                          <Typography variant="body2">{selectedStyleProfile.description}</Typography>
                        ) : null}
                        {selectedStyleProfile.trigger_keywords.length ? (
                          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                            {selectedStyleProfile.trigger_keywords.map((keyword) => (
                              <Chip key={keyword} size="small" variant="outlined" label={keyword} />
                            ))}
                          </Stack>
                        ) : (
                          <Typography variant="body2" color="text.secondary">
                            当前实例没有返回触发关键词。
                          </Typography>
                        )}
                      </Stack>
                    </Box>
                  ) : null}
                </Stack>
              </Box>
            ) : null}

            <Accordion disableGutters variant="outlined" defaultExpanded={Boolean(payload.style || payload.banned || file)}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Stack spacing={0.25}>
                  <Typography variant="subtitle2">补充设定</Typography>
                  <Typography variant="caption" color="text.secondary">
                    文风、禁忌和可选参考文本均可随时补充。
                  </Typography>
                </Stack>
              </AccordionSummary>
              <AccordionDetails sx={{ pt: 0 }}>
                <Stack spacing={2}>
              <TextField
                label={
                  currentCreativeMode === "style_remix"
                    ? "补充风格要求"
                    : currentCreativeMode === "fanfic"
                      ? "补充同人约束"
                      : "风格"
                }
                value={payload.style}
                onChange={updateField("style")}
                placeholder={
                  currentCreativeMode === "style_remix"
                    ? "例如：保留原作的克制叙事，但把人物关系处理得更冷峻，避免过度抒情。"
                    : currentCreativeMode === "fanfic"
                      ? "例如：延续原作世界观与人物关系，但把主线冲突改成都市医院修罗场。"
                    : undefined
                }
              />
              <TextField label="禁忌要求" value={payload.banned} onChange={updateField("banned")} />
              <Stack spacing={1}>
                <Typography variant="subtitle2">上传参考文本（可选）</Typography>
                <Button component="label" variant="outlined" sx={{ alignSelf: "flex-start", maxWidth: "100%" }}>
                  <Typography component="span" noWrap sx={{ maxWidth: 280 }}>
                    {file ? `已选择：${file.name}` : "选择 UTF-8 文本文件"}
                  </Typography>
                  <input hidden type="file" accept=".txt,text/plain" onChange={handleFile} />
                </Button>
              </Stack>
                </Stack>
              </AccordionDetails>
            </Accordion>

          </Stack>
        </CardContent>
      </Card> : null}

      {activeStep === "execution" ? <Card
        component="section"
        id="create-execution"
        className="card-lift"
        sx={{ p: 0, scrollMarginTop: 16, "& .MuiCardContent-root": { p: { xs: 2, sm: 3 } } }}
      >
        <CardContent>
          <Stack spacing={3}>
            <Box>
              <Typography variant="h6" component="h2">篇幅与执行</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                确认单章字数、自动审核和最终创建准备度。
              </Typography>
            </Box>

            <TextField
              label="单章字数下限"
              type="number"
              value={payload.chapter_word_min}
              onChange={updateField("chapter_word_min")}
              helperText="系统会在此基础上按剧情需要上浮 10%-30%。"
            />

            <Box
              id="create-rag-status"
              tabIndex={-1}
              sx={(theme) => ({
                p: 1.5,
                borderRadius: 1.5,
                border: "1px solid",
                borderColor: ragStatus?.available ? "success.main" : "divider",
                bgcolor: alpha(ragStatus?.available ? theme.palette.success.main : theme.palette.warning.main, 0.05),
              })}
            >
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ sm: "center" }}>
                <Box>
                  <Typography variant="subtitle2">小说知识库</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {ragStatus?.available ? "已就绪，可在创建后为创作流程提供检索上下文。" : ragStatus ? "尚未构建，完成同步后才能创建任务。" : "正在检查知识库状态。"}
                  </Typography>
                </Box>
                {ragStatus?.available ? <Chip size="small" color="success" label="已就绪" /> : <Button component={Link} href={settingsRagHref()} size="small">前往同步</Button>}
              </Stack>
            </Box>

            <Box
              sx={(theme) => ({
                p: 2,
                borderRadius: 2,
                border: "1px solid",
                borderColor: "divider",
                backgroundColor: alpha(theme.palette.primary.main, 0.03),
              })}
            >
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "flex-start", sm: "center" }}>
                <FormControlLabel
                  control={
                    <Switch
                      checked={payload.auto_review ?? true}
                      onChange={(e) =>
                        setPayload((curr) => ({ ...curr, auto_review: e.target.checked }))
                      }
                      color="primary"
                    />
                  }
                  label="启用自动审核"
                  sx={{ minHeight: 44 }}
                />
                <Typography variant="body2" color="text.secondary">
                  开启后，大纲/章节/验证阶段将自动通过 AI 审核流转，无需人工介入
                </Typography>
              </Stack>
              {payload.auto_review ? (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  <TextField
                    select
                    label="审核模型模式"
                    value={payload.auto_review_model_mode ?? "follow_creative"}
                    onChange={updateField("auto_review_model_mode")}
                    helperText="跟随模式会让自动审核使用当前任务创作模型；固定模式会始终使用下方审核模型。"
                  >
                    <MenuItem value="follow_creative">跟随当前任务创作模型</MenuItem>
                    <MenuItem value="fixed">固定审核模型</MenuItem>
                  </TextField>
                  {payload.auto_review_model_mode === "fixed" ? (
                    <TextField
                      id="create-review-model"
                      select
                      label="审核模型"
                      value={hasValidReviewModel ? payload.review_model_id : ""}
                      onChange={updateField("review_model_id")}
                      helperText={
                        !selectableModels.length
                          ? "当前没有通过小说工作流兼容性验证的模型"
                          : payload.review_model_id && !hasValidReviewModel
                            ? "当前固定审核模型不可用，请重新选择。"
                            : "固定审核模型只影响自动审核，不影响正文创作。"
                      }
                    >
                      <MenuItem value="">
                        <em>请选择审核模型</em>
                      </MenuItem>
                      {selectableModels.map((option) => (
                        <MenuItem key={option.id} value={option.id}>
                          {(option.display_name || option.id) + (option.provider ? ` · ${option.provider}` : "")}
                        </MenuItem>
                      ))}
                    </TextField>
                  ) : (
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`审核模型：跟随任务创作模型${payload.model_id ? `（${payload.model_id}）` : ""}`}
                      sx={{ alignSelf: "flex-start" }}
                    />
                  )}
                </Stack>
              ) : null}
            </Box>

          </Stack>
        </CardContent>
      </Card> : null}
      <Stack direction={{ xs: "column-reverse", sm: "row" }} spacing={1} justifyContent="space-between">
        <Button startIcon={<ArrowBackIcon />} onClick={() => focusStepField(previousStep)} disabled={isFirstStep}>
          上一步
        </Button>
        {!isLastStep ? (
          <Button endIcon={<ArrowForwardIcon />} variant="contained" onClick={() => focusStepField(nextStep)}>
            下一步
          </Button>
        ) : null}
      </Stack>
      </Stack>
    </Stack>
    <Dialog open={resetConfirmationOpen} onClose={() => setResetConfirmationOpen(false)} aria-labelledby="create-reset-dialog-title">
      <DialogTitle id="create-reset-dialog-title">重置创作设定？</DialogTitle>
      <DialogContent>
        <DialogContentText>这会清空当前表单和已选择的参考文本，无法撤销。</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setResetConfirmationOpen(false)}>取消</Button>
        <Button color="error" variant="contained" onClick={confirmReset}>确认重置</Button>
      </DialogActions>
    </Dialog>
  </WorkbenchPageLayout>
  );
}
