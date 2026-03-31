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
                helperText={models.length ? "模型选项来自后端 /api/models 接口" : "当前后端没有返回可用模型"}
              >
                {models.length ? (
                  models.map((option) => (
                    <MenuItem key={option.id} value={option.id}>
                      {option.id}
                    </MenuItem>
                  ))
                ) : (
                  <MenuItem value="" disabled>
                    暂无可用模型
                  </MenuItem>
                )}
              </TextField>
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
