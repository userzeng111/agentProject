"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  FormControlLabel,
  MenuItem,
  Skeleton,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { NavigateNext as NavigateNextIcon } from "@mui/icons-material";
import { createTask, getModelCatalog, getRagSettings, getStyleProfiles, getTask, normalizeModelOptions, uploadAsset } from "@/lib/api";
import { isNovelTaskModelSupported, selectNovelTaskModels } from "@/lib/model-options.mjs";
import { formatModelRefreshStatus, isCurrentSelectionValid, resolveSelectionAfterRefresh } from "@/features/task-models/model-refresh-state.mjs";
import { settingsHref, workspaceHref } from "@/lib/task-routes";
import { formatCreativeModeLabel, formatNovelSizeLabel, needsStyleProfile, resolveCreativeMode, resolveNovelSize } from "@/lib/task-labels";
import { CreativeMode, ModelOption, ModelRefreshState, NovelSize, RagSettingsStatus, StyleProfile, TaskCreatePayload } from "@/lib/types";

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
};

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
  const [ragStatus, setRagStatus] = useState<RagSettingsStatus | null>(null);
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
      setPayload((current) => {
        if (!current.model_id) {
          return {
            ...current,
            model_id: selectableModelOptions[0]?.id || "",
          };
        }
        return {
          ...current,
          model_id: nextSelection.invalidated ? "" : nextSelection.selectedModelId,
        };
      });
    } catch (loadError) {
      const nextError = loadError instanceof Error ? loadError.message : "读取模型列表失败";
      setError(nextError);
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
          model_id: task.default_model_id ?? input.model_id ?? current.model_id,
          style_profile_id: input.style_profile_id ?? current.style_profile_id,
        }));
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
  const selectableModels = useMemo(
    () => models.filter((item) => isNovelTaskModelSupported(item)),
    [models],
  );
  const resetPayload = useMemo(
    () => ({
      ...defaultPayload,
      model_id: selectableModels.find((item) => item.id === payload.model_id)?.id || selectableModels[0]?.id || "",
    }),
    [payload.model_id, selectableModels],
  );
  const hasValidSelectedModel = isCurrentSelectionValid(payload.model_id, selectableModels);

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
  const canSubmit =
    Boolean(payload.prompt.trim()) &&
    Boolean(hasValidSelectedModel && selectedModel && isNovelTaskModelSupported(selectedModel)) &&
    Number(payload.target_chapter_count || 0) > 0 &&
    (!requiresStyleProfile || Boolean(selectedStyleProfile));
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
      setPayload((current) => ({ ...current, [field]: value }));
    };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const handleSubmit = async () => {
    if (!ragStatus?.available) {
      setError("当前小说知识库尚未构建，请先前往设置页完成全量重建索引。");
      return;
    }
    if (!selectedModel || !isNovelTaskModelSupported(selectedModel)) {
      setError("当前所选模型未完成小说工作流兼容性验证，请改用已验证模型。");
      return;
    }
    if (requiresStyleProfile && !selectedStyleProfile) {
      setError(`请先选择一个有效的${formatCreativeModeLabel(currentCreativeMode)}参考实例。`);
      return;
    }
    try {
      setSubmitting(true);
      setError("");
      const task = await createTask(payload);
      if (file) {
        await uploadAsset(task.id, file);
      }
      router.push(workspaceHref(task.id));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "创建任务失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
    <Stack spacing={3} className="page-fade-in">
      {/* 面包屑 */}
      <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
        <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
          <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
            首页
          </Typography>
        </Link>
        <Typography variant="body2">创建任务</Typography>
      </Breadcrumbs>

      {/* 标题 */}
      <Stack spacing={1}>
        <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
          创建小说任务
        </Typography>
        <Typography color="text.secondary">
          填写创作需求，开始生成大纲，审核通过后继续生成正文。
        </Typography>
      </Stack>

      {ragStatus?.available === false ? (
        <Alert
          severity="warning"
          action={
            <Button component={Link} href={settingsHref()} color="inherit" size="small">
              前往设置
            </Button>
          }
        >
          当前小说知识库未构建，请先前往设置页完成全量重建索引，再开始创作。
        </Alert>
      ) : null}

      {error ? <Alert severity="error">{error}</Alert> : null}

      {/* 表单卡片 */}
      <Card>
        <CardContent>
          <Stack spacing={3}>
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)" },
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
                label="目标总章节数"
                type="number"
                value={payload.target_chapter_count ?? ""}
                onChange={updateField("target_chapter_count")}
                inputProps={{ min: 1, step: 1 }}
                helperText={`允许浮动范围：${chapterCountRangeText}`}
              />
            </Box>

            {modelsLoading ? (
              <Skeleton variant="rounded" height={56} />
            ) : (
              <Stack spacing={1.5}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                  <Typography variant="subtitle2">生成模型</Typography>
                  <Button size="small" variant="outlined" onClick={() => void loadModels(true)}>
                    刷新模型
                  </Button>
                </Stack>
                <TextField
                  select
                  label="生成模型"
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
                    <em>请选择生成模型</em>
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
              <Box
                sx={{
                  p: 2,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  backgroundColor: "rgba(29, 42, 39, 0.03)",
                }}
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
            )}

            {requiresStyleProfile ? (
              <Box
                sx={{
                  p: 2,
                  borderRadius: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  backgroundColor: "rgba(39, 100, 81, 0.03)",
                }}
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
                      sx={{
                        p: 2,
                        borderRadius: 2,
                        border: "1px solid",
                        borderColor: "divider",
                        backgroundColor: "rgba(29, 42, 39, 0.02)",
                      }}
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

            <TextField
              label="创意提示词"
              value={payload.prompt}
              onChange={updateField("prompt")}
              multiline
              minRows={4}
              placeholder="例如：写一个带有潮湿海港气味的悬疑故事，主角是负责夜航记录的女学者。"
            />

            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr", sm: "repeat(2, 1fr)" },
                gap: 2,
              }}
            >
              <TextField label="题材" value={payload.genre} onChange={updateField("genre")} />
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
              <TextField
                label="单章字数下限"
                type="number"
                value={payload.chapter_word_min}
                onChange={updateField("chapter_word_min")}
                helperText="系统会在此基础上按剧情需要上浮 10%-30%。"
              />
              <TextField label="标题倾向" value={payload.title_hint} onChange={updateField("title_hint")} />
              <TextField label="目标读者" value={payload.audience} onChange={updateField("audience")} />
              <TextField label="禁忌要求" value={payload.banned} onChange={updateField("banned")} />
            </Box>

            <Box
              sx={{
                p: 2,
                borderRadius: 2,
                border: "1px solid",
                borderColor: "divider",
                backgroundColor: "rgba(39, 100, 81, 0.03)",
              }}
            >
              <Stack direction="row" spacing={2} alignItems="center">
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
                  sx={{ flex: 1 }}
                />
                <Typography variant="body2" color="text.secondary">
                  开启后，大纲/章节/验证阶段将自动通过 AI 审核流转，无需人工介入
                </Typography>
              </Stack>
            </Box>

            <Stack spacing={1}>
              <Typography variant="subtitle1">上传参考文本（可选）</Typography>
              <Button component="label" variant="outlined">
                {file ? `已选择：${file.name}` : "选择 UTF-8 文本文件"}
                <input hidden type="file" accept=".txt,text/plain" onChange={handleFile} />
              </Button>
            </Stack>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Button disabled={submitting || !canSubmit} onClick={handleSubmit} variant="contained">
                {submitting ? "正在创建..." : "创建并进入任务页"}
              </Button>
              <Button onClick={() => setPayload(resetPayload)} variant="text">
                重置表单
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    </Stack>
    </Container>
  );
}
