"use client";

import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  Collapse,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Pagination,
  Stack,
  Typography,
} from "@mui/material";
import { Close as CloseIcon } from "@mui/icons-material";
import { resolveChapterProgressPage } from "@/features/task-run/task-run-state.mjs";

const CHAPTERS_PER_PAGE = 5;

export type ChapterProgressItem = {
  number: number;
  title: string;
  goal?: string;
  status: string;
  progress: number;
  updatedAt: string;
  summary?: string;
  contentAvailable?: boolean;
};

export type SelectedChapterContent = {
  number: number;
  title: string;
  summary: string;
  content: string;
};

type ChapterProgressPanelProps = {
  active: boolean;
  chapters: ChapterProgressItem[];
  expanded: boolean;
  selectedChapter: SelectedChapterContent | null;
  dialogOpen: boolean;
  formatEventTime: (value: string) => string;
  onSelectChapter: (chapter: ChapterProgressItem) => void;
  onCloseDialog: () => void;
};

function chapterStatusColor(status: string): "default" | "success" | "warning" | "error" | "info" {
  if (status === "已完成") return "success";
  if (status === "正文生成中" || status === "大纲待审核" || status === "待章节审核") return "warning";
  if (status === "待处理") return "error";
  if (status === "待正文生成") return "info";
  return "default";
}

export default function ChapterProgressPanel({
  active,
  chapters,
  expanded,
  selectedChapter,
  dialogOpen,
  formatEventTime,
  onSelectChapter,
  onCloseDialog,
}: ChapterProgressPanelProps) {
  const [requestedPage, setRequestedPage] = useState(1);
  const titleId = selectedChapter ? `chapter-dialog-title-${selectedChapter.number}` : undefined;
  const descriptionId = selectedChapter ? `chapter-dialog-description-${selectedChapter.number}` : undefined;
  const chapterPage = resolveChapterProgressPage(chapters, requestedPage, CHAPTERS_PER_PAGE);

  useEffect(() => {
    setRequestedPage((current) => Math.min(current, chapterPage.totalPages));
  }, [chapterPage.totalPages]);

  return (
    <>
      {active ? (
        <Collapse in={expanded}>
          <Box data-testid="chapter-progress-panel" sx={{ minWidth: 0 }}>
            {chapterPage.items.length ? (
              <Stack spacing={1.5}>
                <Card component="section" variant="outlined" aria-labelledby="chapter-progress-page-heading" sx={{ minWidth: 0 }}>
                  <CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}>
                    <Stack spacing={1.25}>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Typography id="chapter-progress-page-heading" variant="subtitle2" sx={{ flex: 1, minWidth: 0 }}>
                          第 {chapterPage.start}–{chapterPage.end} 章 · 第 {chapterPage.page}/{chapterPage.totalPages} 页
                        </Typography>
                        <Chip label={`${chapterPage.completedCount} / ${chapterPage.items.length} 已完成`} size="small" variant="outlined" />
                      </Stack>
                      <LinearProgress
                        aria-label={`第 ${chapterPage.start} 至 ${chapterPage.end} 章完成进度：${chapterPage.completedCount} / ${chapterPage.items.length}`}
                        variant="determinate"
                        value={Math.round((chapterPage.completedCount / chapterPage.items.length) * 100)}
                        sx={{ height: 6, borderRadius: 999 }}
                      />
                      <List dense aria-label={`第 ${chapterPage.start} 至 ${chapterPage.end} 章列表`} disablePadding sx={{ minWidth: 0 }}>
                        {chapterPage.items.map((chapter) => {
                          const secondary = [
                            chapter.goal ? `目标：${chapter.goal}` : "",
                            chapter.summary || "",
                            chapter.updatedAt ? formatEventTime(chapter.updatedAt) : "",
                          ].filter(Boolean).join(" · ");
                          const content = (
                            <>
                              <ListItemText
                                sx={{ minWidth: 0, my: 0 }}
                                primary={
                                  <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap sx={{ minWidth: 0 }}>
                                    <Typography component="span" variant="body2" sx={{ overflowWrap: "anywhere", minWidth: 0 }}>
                                      {`第 ${chapter.number} 章 · ${chapter.title}`}
                                    </Typography>
                                    <Chip label={chapter.status} size="small" color={chapterStatusColor(chapter.status)} />
                                  </Stack>
                                }
                                secondary={secondary || "等待章节状态更新。"}
                                secondaryTypographyProps={{
                                  sx: {
                                    mt: 0.25,
                                    whiteSpace: "pre-line",
                                    overflowWrap: "anywhere",
                                  },
                                }}
                              />
                              <LinearProgress
                                aria-label={`第 ${chapter.number} 章进度：${chapter.status}`}
                                variant="determinate"
                                value={chapter.progress}
                                sx={{ mt: 0.75, height: 4, borderRadius: 999 }}
                              />
                            </>
                          );
                          return (
                            <ListItem key={chapter.number} disableGutters divider alignItems="flex-start" sx={{ minWidth: 0 }}>
                              {chapter.contentAvailable ? (
                                <ListItemButton
                                  aria-label={`查看第 ${chapter.number} 章正文：${chapter.title}`}
                                  onClick={() => onSelectChapter(chapter)}
                                  sx={{ py: 1, minWidth: 0, minHeight: 44, alignItems: "flex-start", borderRadius: 1 }}
                                >
                                  <Box sx={{ minWidth: 0, width: "100%" }}>{content}</Box>
                                </ListItemButton>
                              ) : (
                                <Box sx={{ py: 1, px: 1.5, minWidth: 0, width: "100%" }}>{content}</Box>
                              )}
                            </ListItem>
                          );
                        })}
                      </List>
                    </Stack>
                  </CardContent>
                </Card>
                {chapterPage.totalPages > 1 ? (
                  <Box component="nav" aria-label="章节进度分页" sx={{ display: "flex", justifyContent: "center", minWidth: 0 }}>
                    <Pagination
                      count={chapterPage.totalPages}
                      page={chapterPage.page}
                      onChange={(_, nextPage) => setRequestedPage(nextPage)}
                      shape="rounded"
                      siblingCount={1}
                      boundaryCount={1}
                      sx={{
                        "& .MuiPagination-ul": { flexWrap: "wrap", justifyContent: "center" },
                        "& .MuiPaginationItem-root": { minWidth: 44, minHeight: 44 },
                      }}
                    />
                  </Box>
                ) : null}
              </Stack>
            ) : (
              <Alert severity="info">当前还没有章节级进度事件。</Alert>
            )}
          </Box>
        </Collapse>
      ) : null}

      <Dialog
        open={dialogOpen}
        onClose={onCloseDialog}
        maxWidth="md"
        fullWidth
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        {selectedChapter && (
          <>
            <DialogTitle id={titleId}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={2} sx={{ minWidth: 0 }}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography
                    variant="h5"
                    component="span"
                    sx={{
                      display: "block",
                      overflowWrap: "anywhere",
                    }}
                  >
                    第 {selectedChapter.number} 章：{selectedChapter.title}
                  </Typography>
                  {selectedChapter.summary ? (
                    <Typography
                      id={descriptionId}
                      variant="body2"
                      color="text.secondary"
                      sx={{ mt: 0.5, overflowWrap: "anywhere" }}
                    >
                      {selectedChapter.summary}
                    </Typography>
                  ) : (
                    <Typography id={descriptionId} component="span" sx={{ display: "none" }}>
                      章节正文内容
                    </Typography>
                  )}
                </Box>
                <IconButton aria-label="关闭章节正文" onClick={onCloseDialog} edge="end">
                  <CloseIcon />
                </IconButton>
              </Stack>
            </DialogTitle>
            <DialogContent dividers>
              <Typography
                component="pre"
                sx={{
                  fontFamily: "inherit",
                  fontSize: 15,
                  lineHeight: 1.8,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  overflowWrap: "anywhere",
                  m: 0,
                }}
              >
                {selectedChapter.content}
              </Typography>
            </DialogContent>
          </>
        )}
      </Dialog>
    </>
  );
}
