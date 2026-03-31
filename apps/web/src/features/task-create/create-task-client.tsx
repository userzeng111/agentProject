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
  MenuItem,
  Skeleton,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { NavigateNext as NavigateNextIcon } from "@mui/icons-material";
import { createTask, getModels, normalizeModelOptions, uploadAsset } from "@/lib/api";
import { ModelOption, TaskCreatePayload, TaskMode } from "@/lib/types";

const defaultPayload: TaskCreatePayload = {
  mode: "short_story",
  prompt: "",
  genre: "",
  style: "",
  target_words: 1800,
  audience: "",
  banned: "",
  title_hint: "",
  model_id: "",
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

export default function CreateTaskClient() {
  const router = useRouter();
  const [payload, setPayload] = useState(defaultPayload);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

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
  const modelFeatures = useMemo(
    () =>
      Array.isArray(selectedModelCapabilities?.features)
        ? selectedModelCapabilities.features.slice(0, 6)
        : [],
    [selectedModelCapabilities],
  );

  const updateField =
    (field: keyof TaskCreatePayload) =>
    (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      const value = field === "target_words" ? Number(event.target.value) : event.target.value;
      setPayload((current) => ({ ...current, [field]: value }));
    };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const handleSubmit = async () => {
    try {
      setSubmitting(true);
      setError("");
      const task = await createTask(payload);
      if (file) {
        await uploadAsset(task.id, file);
      }
      router.push(`/tasks/${task.id}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "创建任务失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
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

      {error ? <Alert severity="error">{error}</Alert> : null}

      {/* 表单卡片 */}
      <Card>
        <CardContent>
          <Stack spacing={3}>
            <TextField
              select
              label="任务模式"
              value={payload.mode}
              onChange={updateField("mode")}
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
              <TextField label="风格" value={payload.style} onChange={updateField("style")} />
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

            <Stack spacing={1}>
              <Typography variant="subtitle1">上传参考文本（可选）</Typography>
              <Button component="label" variant="outlined">
                {file ? `已选择：${file.name}` : "选择 UTF-8 文本文件"}
                <input hidden type="file" accept=".txt,text/plain" onChange={handleFile} />
              </Button>
            </Stack>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Button disabled={submitting || !payload.prompt.trim()} onClick={handleSubmit} variant="contained">
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
  );
}
