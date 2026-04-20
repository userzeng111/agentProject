"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
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
import { createTask, getModels, getRagSettings, getStyleProfiles, getTask, normalizeModelOptions, uploadAsset } from "@/lib/api";
import { settingsHref, workspaceHref } from "@/lib/task-routes";
import { ModelOption, RagSettingsStatus, StyleProfile, TaskCreatePayload, TaskMode } from "@/lib/types";

const defaultPayload: TaskCreatePayload = {
  mode: "short_story",
  prompt: "",
  genre: "",
  style: "",
  style_profile_id: "",
  target_words: 1800,
  audience: "",
  banned: "",
  title_hint: "",
  model_id: "",
  auto_review: true,
};

const modeOptions: { value: TaskMode; label: string }[] = [
  { value: "short_story", label: "短篇生成" },
  { value: "long_story", label: "长篇生成" },
  { value: "fanfic", label: "同人创作" },
  { value: "style_remix", label: "风格复刻" },
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
  const [styleProfiles, setStyleProfiles] = useState<StyleProfile[]>([]);
  const [styleProfilesLoading, setStyleProfilesLoading] = useState(true);
  const [styleProfilesError, setStyleProfilesError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [retryLoaded, setRetryLoaded] = useState(false);
  const [ragStatus, setRagStatus] = useState<RagSettingsStatus | null>(null);

  useEffect(() => {
    async function loadModels() {
      try {
        setModelsLoading(true);
        const nextModels = normalizeModelOptions(await getModels());
        setModels(nextModels);
        setPayload((current) => ({
          ...current,
          model_id: current.model_id || nextModels[0]?.id || "",
        }));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "读取模型列表失败");
      } finally {
        setModelsLoading(false);
      }
    }

    void loadModels();
  }, []);

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
          genre: input.genre ?? current.genre,
          style: input.style ?? current.style,
          target_words: input.target_words ?? current.target_words,
          audience: input.audience ?? current.audience,
          banned: input.banned ?? current.banned,
          title_hint: input.title_hint ?? current.title_hint,
          mode: task.mode ?? current.mode,
          model_id: input.model_id ?? current.model_id,
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

  const resetPayload = useMemo(
    () => ({
      ...defaultPayload,
      model_id: payload.model_id || models[0]?.id || "",
    }),
    [models, payload.model_id],
  );

  const selectedModel = useMemo(
    () => models.find((item) => item.id === payload.model_id) ?? models[0],
    [models, payload.model_id],
  );

  const selectedModelCapabilities = selectedModel?.capabilities;
  const selectedStyleProfile = useMemo(
    () => styleProfiles.find((item) => item.id === payload.style_profile_id) ?? null,
    [payload.style_profile_id, styleProfiles],
  );
  const canSubmit = Boolean(payload.prompt.trim()) && (payload.mode !== "style_remix" || Boolean(selectedStyleProfile));
  const modelFeatures = useMemo(
    () =>
      Array.isArray(selectedModelCapabilities?.features)
        ? selectedModelCapabilities.features.slice(0, 6)
        : [],
    [selectedModelCapabilities],
  );

  useEffect(() => {
    if (payload.mode !== "style_remix") {
      return;
    }
    setPayload((current) => {
      if (current.mode !== "style_remix" || current.style_profile_id || !styleProfiles.length) {
        return current;
      }
      return {
        ...current,
        style_profile_id: styleProfiles[0].id,
      };
    });
  }, [payload.mode, styleProfiles]);

  const updateField =
    (field: keyof TaskCreatePayload) =>
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const value = field === "target_words" ? Number(event.target.value) : event.target.value;
      setPayload((current) => ({ ...current, [field]: value }));
    };

  const handleModeChange = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const nextMode = event.target.value as TaskMode;
    setPayload((current) => ({ ...current, mode: nextMode }));
  };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const handleSubmit = async () => {
    if (!ragStatus?.available) {
      setError("当前小说知识库尚未构建，请先前往设置页完成全量重建索引。");
      return;
    }
    if (payload.mode === "style_remix" && !selectedStyleProfile) {
      setError("请先选择一个有效的风格实例。");
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
            <TextField
              select
              label="任务模式"
              value={payload.mode}
              onChange={handleModeChange}
            >
              {modeOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>

            {modelsLoading ? (
              <Skeleton variant="rounded" height={56} />
            ) : (
              <TextField
                select
                label="生成模型"
                value={payload.model_id ?? ""}
                onChange={updateField("model_id")}
                helperText={
                  models.length
                    ? "模型选项来自后端 /api/models 接口，能力字段缺失时会自动兼容。"
                    : "当前后端没有返回可用模型"
                }
              >
                {models.length ? (
                  models.map((option) => (
                    <MenuItem key={option.id} value={option.id}>
                      {option.display_name || option.id}
                    </MenuItem>
                  ))
                ) : (
                  <MenuItem value="" disabled>
                    暂无可用模型
                  </MenuItem>
                )}
              </TextField>
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

            {payload.mode === "style_remix" ? (
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
                      <Typography variant="subtitle1">风格实例</Typography>
                      <Typography variant="body2" color="text.secondary">
                        从后端 `GET /api/style-profiles` 拉取实例列表，选择后会作为风格复刻基础。
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
                      label="风格实例"
                      value={payload.style_profile_id}
                      onChange={updateField("style_profile_id")}
                      helperText={
                        styleProfilesError
                          ? styleProfilesError
                          : styleProfiles.length
                            ? "选择一个已蒸馏的实例，再用下方文本补充具体写作要求。"
                            : "当前没有可用的风格实例，普通模式不受影响。"
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
                label={payload.mode === "style_remix" ? "补充风格要求" : "风格"}
                value={payload.style}
                onChange={updateField("style")}
                placeholder={
                  payload.mode === "style_remix"
                    ? "例如：保留原作的克制叙事，但把人物关系处理得更冷峻，避免过度抒情。"
                    : undefined
                }
              />
              <TextField
                label="目标字数"
                type="number"
                value={payload.target_words}
                onChange={updateField("target_words")}
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
