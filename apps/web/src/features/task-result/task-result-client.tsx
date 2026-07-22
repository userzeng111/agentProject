"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Container,
  List,
  ListItem,
  ListItemText,
  Snackbar,
  Stack,
  Typography,
} from "@mui/material";
import { archiveTask, fetchTextRef, getApiBase, getResult } from "@/lib/api";
import { projectViewHref, workspaceHref } from "@/lib/task-routes";
import { ResultResponse } from "@/lib/types";
import { NovelReader } from "@/components/novel-reader";
import { ProjectShell } from "@/components/project-shell";
import { StageNav } from "@/components/stage-nav";

const WORKFLOW_STEPS = [
  { label: "创建" },
  { label: "运行" },
  { label: "审核" },
  { label: "结果" },
];

export default function TaskResultClient({ taskId }: { taskId?: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const resolvedTaskId = taskId || searchParams.get("id") || "";
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [resultMarkdown, setResultMarkdown] = useState("");
  const [loading, setLoading] = useState(true);
  const [archiving, setArchiving] = useState(false);
  const [error, setError] = useState("");
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMsg, setSnackbarMsg] = useState("");

  /** 显示 snackbar 提示 */
  const showSnackbar = useCallback((msg: string) => {
    setSnackbarMsg(msg);
    setSnackbarOpen(true);
  }, []);

  /** 复制全文到剪贴板 */
  const handleCopy = useCallback(async () => {
    if (!resultMarkdown) return;
    try {
      await navigator.clipboard.writeText(resultMarkdown);
      showSnackbar("已复制到剪贴板");
    } catch {
      showSnackbar("复制失败，请手动选择复制");
    }
  }, [resultMarkdown, showSnackbar]);

  /** 导出为 Markdown 文件下载 */
  const handleExportMd = useCallback(() => {
    if (!resultMarkdown) return;
    const blob = new Blob([resultMarkdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result?.meta.title || resolvedTaskId || "novel"}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showSnackbar("已导出 Markdown 文件");
  }, [resultMarkdown, result?.meta.title, resolvedTaskId, showSnackbar]);

  const handleArchive = useCallback(async () => {
    if (!resolvedTaskId || archiving) return;
    if (!window.confirm("确认已检查生成结果并归档？归档后可在归档库中查看。")) return;
    setArchiving(true);
    try {
      await archiveTask(resolvedTaskId);
      showSnackbar("任务已归档");
      router.push(projectViewHref(resolvedTaskId, "archive"));
    } catch (archiveError) {
      setError(archiveError instanceof Error ? archiveError.message : "归档失败");
      showSnackbar("归档失败");
    } finally {
      setArchiving(false);
    }
  }, [archiving, resolvedTaskId, router, showSnackbar]);

  const load = useCallback(async () => {
    if (!resolvedTaskId) {
      setError("缺少任务 ID");
      setResult(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const response = await getResult(resolvedTaskId);
      setResult(response);
      setResultMarkdown(response.result_markdown ?? "");
      setError("");

      if (!response.result_markdown && response.result_md_ref) {
        const markdown = await fetchTextRef(response.result_md_ref);
        setResultMarkdown(markdown);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "读取结果失败");
    } finally {
      setLoading(false);
    }
  }, [resolvedTaskId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !result) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Box sx={{ py: 6 }}>
          <Typography>正在读取结果...</Typography>
        </Box>
      </Container>
    );
  }

  if (!result) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Stack spacing={2} sx={{ py: 6 }}>
          <Alert severity="error">{error || "读取结果失败"}</Alert>
          <Box>
            <Button variant="outlined" onClick={() => void load()}>
              重新加载
            </Button>
          </Box>
        </Stack>
      </Container>
    );
  }

  const resolveRefHref = (ref?: string | null) => {
    if (!ref) {
      return undefined;
    }
    return ref.startsWith("http") ? ref : `${getApiBase()}${ref}`;
  };
  const canArchive = result.meta.status === "completed" && result.meta.storage_state !== "archive";

  return (
    <ProjectShell
      breadcrumbs={[
        { label: "首页", href: "/" },
        { label: "工作台", href: workspaceHref(resolvedTaskId) },
        { label: "生成结果" },
      ]}
      title="生成结果"
      metaItems={[
        { label: result.meta.title || resolvedTaskId },
        { label: result.meta.status, variant: "outlined" },
      ]}
      actions={
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {resultMarkdown ? (
            <>
              <Button size="small" variant="outlined" onClick={() => void handleCopy()}>
                复制全文
              </Button>
              <Button size="small" variant="outlined" onClick={handleExportMd}>
                导出 MD
              </Button>
            </>
          ) : null}
          {canArchive ? (
            <Button variant="contained" size="small" disabled={archiving} onClick={() => void handleArchive()}>
              {archiving ? "归档中..." : "确认归档"}
            </Button>
          ) : null}
          <Button component={Link} href={workspaceHref(resolvedTaskId)} variant="outlined" size="small">
            返回工作台
          </Button>
        </Stack>
      }
      stageNav={<StageNav stages={WORKFLOW_STEPS} activeStep={3} />}
    >

      {error ? <Alert severity="error">{error}</Alert> : null}

      {/* 结果摘要 */}
      <Card className="card-lift">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">结果摘要</Typography>
            <Typography>{result.result_summary || result.meta.summary || "暂无结果摘要"}</Typography>
          </Stack>
        </CardContent>
      </Card>

      {result.chapter_index.length ? <NovelReader chapters={result.chapter_index} /> : null}

      {/* 章节索引 */}
      <Card className="card-lift">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">章节索引</Typography>
            <List dense>
              {result.chapter_index.length ? (
                result.chapter_index.map((chapter) => (
                  <ListItem key={`${chapter.number}-${chapter.title}`} disableGutters>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      spacing={1}
                      justifyContent="space-between"
                      alignItems={{ xs: "flex-start", sm: "center" }}
                      sx={{ width: "100%" }}
                    >
                      <ListItemText
                        primary={`第 ${chapter.number} 章 · ${chapter.title}`}
                        secondary={[chapter.summary, chapter.content ? "已内联正文" : ""].filter(Boolean).join(" · ")}
                      />
                      {chapter.md_ref ? (
                        <Button
                          component="a"
                          href={resolveRefHref(chapter.md_ref)}
                          target="_blank"
                          rel="noreferrer"
                          size="small"
                        >
                          查看章节文件
                        </Button>
                      ) : null}
                    </Stack>
                  </ListItem>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="暂无章节索引。" />
                </ListItem>
              )}
            </List>
          </Stack>
        </CardContent>
      </Card>

      {/* 工件索引 */}
      {result.artifact_index.length ? (
        <Card className="card-lift">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">工件索引</Typography>
              <List dense>
                {result.artifact_index.map((artifact) => (
                  <ListItem key={artifact.id} disableGutters>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      spacing={1}
                      justifyContent="space-between"
                      alignItems={{ xs: "flex-start", sm: "center" }}
                      sx={{ width: "100%" }}
                    >
                      <ListItemText primary={artifact.name} secondary={artifact.type} />
                      <Stack direction="row" spacing={1}>
                        {artifact.md_ref ? (
                          <Button
                            component="a"
                            href={resolveRefHref(artifact.md_ref)}
                            target="_blank"
                            rel="noreferrer"
                            size="small"
                          >
                            查看文本
                          </Button>
                        ) : null}
                        {artifact.json_ref ? (
                          <Button
                            component="a"
                            href={resolveRefHref(artifact.json_ref)}
                            target="_blank"
                            rel="noreferrer"
                            size="small"
                          >
                            查看 JSON
                          </Button>
                        ) : null}
                      </Stack>
                    </Stack>
                  </ListItem>
                ))}
              </List>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {/* 历史记录 */}
      {result.history_index?.length ? (
        <Card className="card-lift">
          <CardContent>
            <Stack spacing={2}>
              <Typography variant="h5">历史记录</Typography>
              <List dense>
                {result.history_index.map((item, index) => (
                  <ListItem key={`${item.version}-${item.created_at ?? index}`} disableGutters>
                    <ListItemText
                      primary={`${item.version} · ${item.action}`}
                      secondary={[
                        item.comment,
                        item.created_at ? new Date(item.created_at).toLocaleString() : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    />
                  </ListItem>
                ))}
              </List>
            </Stack>
          </CardContent>
        </Card>
      ) : null}
    {/* 操作反馈提示 */}
    <Snackbar
      open={snackbarOpen}
      autoHideDuration={2500}
      onClose={() => setSnackbarOpen(false)}
      message={snackbarMsg}
      anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
    />
    </ProjectShell>
  );
}
