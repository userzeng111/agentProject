"use client";

import {
  Alert,
  Box,
  Chip,
  Collapse,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { Close as CloseIcon } from "@mui/icons-material";

export type ChapterProgressItem = {
  number: number;
  title: string;
  status: string;
  progress: number;
  updatedAt: string;
  summary?: string;
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
  const titleId = selectedChapter ? `chapter-dialog-title-${selectedChapter.number}` : undefined;
  const descriptionId = selectedChapter ? `chapter-dialog-description-${selectedChapter.number}` : undefined;

  return (
    <>
      {active ? (
        <Collapse in={expanded}>
          <Box data-testid="chapter-progress-panel" sx={{ minWidth: 0 }}>
            {chapters.length ? (
              <List dense aria-label="章节进度列表" sx={{ minWidth: 0 }}>
                {chapters.map((chapter) => (
                  <Box key={chapter.number} component="li" sx={{ listStyle: "none", minWidth: 0 }}>
                    <ListItem component="div" disableGutters alignItems="flex-start" sx={{ minWidth: 0 }}>
                      <ListItemButton
                        aria-label={`查看第 ${chapter.number} 章正文：${chapter.title}`}
                        onClick={() => onSelectChapter(chapter)}
                        sx={{ py: 1, minWidth: 0, alignItems: "flex-start" }}
                      >
                        <ListItemText
                          sx={{ minWidth: 0 }}
                          primary={
                            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ minWidth: 0 }}>
                              <Typography component="span" sx={{ overflowWrap: "anywhere", minWidth: 0 }}>
                                {`第 ${chapter.number} 章 · ${chapter.title}`}
                              </Typography>
                              <Chip
                                label={chapter.status}
                                size="small"
                                color={chapter.status === "已完成" ? "success" : "default"}
                              />
                            </Stack>
                          }
                          secondary={[formatEventTime(chapter.updatedAt), chapter.summary || ""].filter(Boolean).join(" · ")}
                          secondaryTypographyProps={{
                            sx: {
                              whiteSpace: "pre-line",
                              overflowWrap: "anywhere",
                            },
                          }}
                        />
                      </ListItemButton>
                    </ListItem>
                    <LinearProgress
                      aria-label={`第 ${chapter.number} 章进度`}
                      variant="determinate"
                      value={chapter.progress}
                      sx={{ mb: 1.5, height: 8, borderRadius: 999 }}
                    />
                    <Divider component="div" />
                  </Box>
                ))}
              </List>
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
