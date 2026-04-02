"use client";

import { useEffect, useState } from "react";
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
  Divider,
  List,
  ListItem,
  ListItemText,
  LinearProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  NavigateNext as NavigateNextIcon,
  CheckCircle as CheckCircleIcon,
  Edit as EditIcon,
  PlayArrow as PlayIcon,
  MenuBook as MenuBookIcon,
  Article as ArticleIcon,
  Verified as VerifiedIcon,
} from "@mui/icons-material";
import { fetchTextRef, getReview, resumeTask } from "@/lib/api";
import { ReviewResponse } from "@/lib/types";

const OUTLINE_STEPS = [
  { label: "创建", icon: <EditIcon fontSize="small" /> },
  { label: "大纲", icon: <ArticleIcon fontSize="small" /> },
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

function StepIndicator({ steps, activeStep }: { steps: typeof OUTLINE_STEPS; activeStep: number }) {
  return (
    <Card className="glass-card">
      <CardContent sx={{ py: 2 }}>
        <Stack direction="row" justifyContent="center" spacing={0} sx={{ width: "100%" }}>
          {steps.map((step, index) => {
            const isDone = index < activeStep;
            const isActive = index === activeStep;
            return (
              <Box
                key={step.label}
                sx={{
                  display: "flex",
                  alignItems: "center",
                  flex: index < steps.length - 1 ? 1 : 0,
                  justifyContent: "center",
                }}
              >
                <Stack spacing={0.5} alignItems="center" sx={{ minWidth: 64 }}>
                  <Box
                    sx={{
                      width: 36,
                      height: 36,
                      borderRadius: "50%",
                      display: "grid",
                      placeItems: "center",
                      backgroundColor: isDone ? "success.main" : isActive ? "primary.main" : "rgba(29,42,39,0.08)",
                      color: "#fff",
                      transition: "all 0.3s",
                    }}
                  >
                    {isDone ? <CheckCircleIcon fontSize="small" /> : step.icon}
                  </Box>
                  <Typography
                    variant="caption"
                    sx={{
                      fontWeight: isActive ? 600 : 400,
                      color: isActive ? "primary.main" : isDone ? "success.main" : "text.secondary",
                    }}
                  >
                    {step.label}
                  </Typography>
                </Stack>
                {index < steps.length - 1 && (
                  <Box
                    sx={{
                      flex: 1,
                      height: 2,
                      mx: 1,
                      mt: -2,
                      backgroundColor: isDone ? "success.main" : "rgba(29,42,39,0.08)",
                      transition: "all 0.3s",
                      borderRadius: 1,
                    }}
                  />
                )}
              </Box>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
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

function OutlineReview({
  review,
  outlineMarkdown,
  comment,
  setComment,
  submitting,
  onDecision,
  error,
}: {
  review: ReviewResponse;
  outlineMarkdown: string;
  comment: string;
  setComment: (v: string) => void;
  submitting: boolean;
  onDecision: (approved: boolean) => void;
  error: string;
}) {
  const revisionCount = (review as ReviewResponse & { revision_count?: number }).revision_count ?? 0;
  return (
    <>
      <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
        大纲审核
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip label={review.meta.title || review.meta.task_id} size="small" />
        <Chip label={`版本 ${review.review_version}`} size="small" variant="outlined" />
        <Chip label={`审核第 ${revisionCount + 1} 轮`} size="small" variant="outlined" />
        <Chip label={review.review_type} size="small" variant="outlined" />
      </Stack>

      {error ? <Alert severity="error">{error}</Alert> : null}

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">审核摘要</Typography>
            <Typography>{review.summary || review.meta.summary || "暂无审核摘要"}</Typography>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">风险提示</Typography>
            <List dense>
              {review.risk_flags.length ? (
                review.risk_flags.map((flag, index) => (
                  <ListItem key={`${flag}-${index}`} disableGutters>
                    <Chip label={flag} size="small" color="warning" variant="outlined" sx={{ mr: 1 }} />
                  </ListItem>
                ))
              ) : (
                <ListItem disableGutters>
                  <ListItemText primary="当前没有风险提示。" />
                </ListItem>
              )}
            </List>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">大纲内容</Typography>
            {outlineMarkdown ? (
              <Typography
                component="pre"
                sx={{ fontFamily: "inherit", fontSize: 15, lineHeight: 1.8, whiteSpace: "pre-wrap" }}
              >
                {outlineMarkdown}
              </Typography>
            ) : (
              <Alert severity="info">暂无大纲内容。</Alert>
            )}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">审核操作</Typography>
            <ReviewHistory history={review.review_history} />
            <TextField
              label="审核意见"
              multiline
              minRows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="例如：通过；或者要求收束得更克制一些。"
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Button disabled={submitting} variant="contained" onClick={() => onDecision(true)}>
                通过并进入正文
              </Button>
              <Button disabled={submitting} variant="outlined" color="error" onClick={() => onDecision(false)}>
                拒绝并修订
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    </>
  );
}

function ChapterPairReview({
  review,
  comment,
  setComment,
  submitting,
  onDecision,
  error,
}: {
  review: ReviewResponse;
  comment: string;
  setComment: (v: string) => void;
  submitting: boolean;
  onDecision: (approved: boolean) => void;
  error: string;
}) {
  const chapters = review.chapter_pair || [];
  const batchIndex = review.batch_index ?? 0;
  const completed = review.completed_count ?? 0;
  const total = review.total_chapters ?? 0;
  const revisionCount = review.chapter_pair_revision_count ?? 0;
  const pairNumber = Math.floor(batchIndex / 2) + 1;

  return (
    <>
      <Typography variant="h3" sx={{ fontFamily: "var(--font-serif-sc)" }}>
        章节对审核
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip label={review.meta.title || review.meta.task_id} size="small" />
        <Chip label={`第 ${pairNumber} 对`} size="small" color="primary" />
        <Chip label={`${completed}/${total} 章`} size="small" variant="outlined" />
        {revisionCount > 0 && (
          <Chip label={`修订第 ${revisionCount + 1} 轮`} size="small" variant="outlined" color="warning" />
        )}
      </Stack>

      {error ? <Alert severity="error">{error}</Alert> : null}

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
              已完成 {completed} / {total} 章，正在审核第 {batchIndex + 1}–{Math.min(batchIndex + 2, total)} 章
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">审核摘要</Typography>
            <Typography>{review.summary || review.meta.summary || "请审核这对章节是否符合大纲要求。"}</Typography>
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
              <Typography
                component="pre"
                sx={{ fontFamily: "inherit", fontSize: 15, lineHeight: 1.8, whiteSpace: "pre-wrap" }}
              >
                {chapter.content}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      ))}

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">审核操作</Typography>
            <ReviewHistory history={review.review_history} />
            <TextField
              label="审核意见"
              multiline
              minRows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="例如：通过；或者第 3 段逻辑不够顺畅，请加强。"
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Button disabled={submitting} variant="contained" onClick={() => onDecision(true)}>
                通过并继续
              </Button>
              <Button disabled={submitting} variant="outlined" color="error" onClick={() => onDecision(false)}>
                拒绝并修订
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    </>
  );
}

function VerificationReview({
  review,
  comment,
  setComment,
  submitting,
  onDecision,
  error,
}: {
  review: ReviewResponse;
  comment: string;
  setComment: (v: string) => void;
  submitting: boolean;
  onDecision: (approved: boolean) => void;
  error: string;
}) {
  const report = review.verification_report || {};
  const issues = report.issues || [];
  const score = report.overall_score ?? 0;
  const revisionCount = review.verification_revision_count ?? 0;

  const scoreColor = score >= 80 ? "success" : score >= 60 ? "warning" : "error";

  return (
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

      {error ? <Alert severity="error">{error}</Alert> : null}

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

      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="h5">审核操作</Typography>
            <ReviewHistory history={review.review_history} />
            <TextField
              label="审核意见"
              multiline
              minRows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="例如：通过；或者人物前后不一致，请修复后再审。"
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <Button disabled={submitting} variant="contained" onClick={() => onDecision(true)}>
                通过并生成正文
              </Button>
              <Button disabled={submitting} variant="outlined" color="error" onClick={() => onDecision(false)}>
                拒绝并修复
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    </>
  );
}

export default function TaskReviewClient({ taskId }: { taskId: string }) {
  const router = useRouter();
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [outlineMarkdown, setOutlineMarkdown] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadReview() {
      try {
        const nextReview = await getReview(taskId);
        setReview(nextReview);
        setOutlineMarkdown(nextReview.outline_markdown ?? "");
        setError("");

        if (!nextReview.outline_markdown && nextReview.outline_md_ref) {
          const markdown = await fetchTextRef(nextReview.outline_md_ref);
          setOutlineMarkdown(markdown);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "读取审核信息失败");
      }
    }

    void loadReview();
  }, [taskId]);

  async function handleDecision(approved: boolean) {
    try {
      setSubmitting(true);
      const nextTask = await resumeTask(taskId, approved, comment);
      setError("");
      if (nextTask.status === "completed") {
        router.push(`/result/${taskId}`);
      } else if (
        nextTask.status === "waiting_outline_review" ||
        nextTask.status === "waiting_chapter_review" ||
        nextTask.status === "waiting_verification_review"
      ) {
        // 刷新审核页
        router.push(`/review/${taskId}`);
      } else {
        router.push(`/tasks/${taskId}`);
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "提交审核失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (!review) {
    return (
      <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
        <Box sx={{ py: 6 }}>
          <Typography>正在载入审核信息...</Typography>
        </Box>
      </Container>
    );
  }

  const reviewType = review.review_type || "outline_review";
  const activeStep =
    reviewType === "outline_review"
      ? 2
      : reviewType === "chapter_pair_review"
        ? 3
        : reviewType === "verification_review"
          ? 3
          : 2;
  const steps =
    reviewType === "outline_review"
      ? OUTLINE_STEPS
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
    <Container maxWidth="md" sx={{ py: 3, px: { xs: 2, sm: 3 } }}>
      <Stack spacing={3} className="page-fade-in">
        {/* 面包屑 */}
        <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
          <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
            <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
              首页
            </Typography>
          </Link>
          <Link href={`/tasks/${taskId}`} style={{ color: "inherit", textDecoration: "none" }}>
            <Typography variant="body2" color="text.secondary" sx={{ "&:hover": { color: "primary.main" } }}>
              工作台
            </Typography>
          </Link>
          <Typography variant="body2">{breadcrumbLabel}</Typography>
        </Breadcrumbs>

        {/* 步骤指示器 */}
        <StepIndicator steps={steps} activeStep={activeStep} />

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
          />
        )}
      </Stack>
    </Container>
  );
}
