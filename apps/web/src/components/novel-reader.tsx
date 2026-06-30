"use client";

import { useState } from "react";
import { Alert, Box, Button, Divider, Pagination, Paper, Stack, Typography } from "@mui/material";
import MarkdownContent from "@/components/markdown-content";
import { ResultChapterItem } from "@/lib/types";

export type NovelReaderState = {
  page: number;
  totalPages: number;
  chapter: ResultChapterItem | null;
};

export function resolveNovelReaderPage(chapters: ResultChapterItem[], requestedPage: number): NovelReaderState {
  const totalPages = chapters.length;
  if (totalPages === 0) {
    return { page: 1, totalPages: 0, chapter: null };
  }
  const normalizedPage = Math.min(Math.max(Math.trunc(requestedPage), 1), totalPages);
  return {
    page: normalizedPage,
    totalPages,
    chapter: chapters[normalizedPage - 1] ?? null,
  };
}

function ReaderNav({
  page,
  totalPages,
  onPrev,
  onNext,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
  onPageChange: (page: number) => void;
}) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        gap: 2,
        flexWrap: "wrap",
        bgcolor: "background.paper",
        borderRadius: 2,
        border: "1px solid",
        borderColor: "divider",
        minWidth: 0,
      }}
    >
      <Button variant="outlined" size="small" disabled={page <= 1} onClick={onPrev}>
        上一章
      </Button>
      <Typography variant="body2" color="text.secondary">
        第 {page} / {totalPages} 章
      </Typography>
      <Button variant="outlined" size="small" disabled={page >= totalPages} onClick={onNext}>
        下一章
      </Button>
      <Pagination
        count={totalPages}
        page={page}
        onChange={(_, nextPage) => onPageChange(nextPage)}
        size="small"
        shape="rounded"
        siblingCount={1}
      />
    </Paper>
  );
}

export function NovelReader({ chapters }: { chapters: ResultChapterItem[] }) {
  const [page, setPage] = useState(1);
  const { page: currentPage, totalPages, chapter } = resolveNovelReaderPage(chapters, page);

  const changePage = (nextPage: number) => {
    setPage(nextPage);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (totalPages === 0 || !chapter) {
    return <Alert severity="info">当前任务没有章节内容。</Alert>;
  }

  return (
    <Stack spacing={2} data-testid="novel-reader" sx={{ minWidth: 0 }}>
      <ReaderNav
        page={currentPage}
        totalPages={totalPages}
        onPrev={() => changePage(currentPage - 1)}
        onNext={() => changePage(currentPage + 1)}
        onPageChange={changePage}
      />

      <Paper
        elevation={1}
        sx={{
          p: { xs: 3, sm: 4, md: 5 },
          bgcolor: "background.paper",
          color: "text.primary",
          borderRadius: 2,
          border: "1px solid",
          borderColor: "divider",
          minWidth: 0,
        }}
      >
        <Stack spacing={3}>
          <Box textAlign="center" sx={{ mb: 2, minWidth: 0 }}>
            <Typography
              component="h3"
              variant="h4"
              sx={{
                fontFamily: "var(--font-serif-sc)",
                fontWeight: 700,
                fontSize: { xs: "1.5rem", md: "1.75rem" },
                lineHeight: 1.4,
                overflowWrap: "anywhere",
              }}
            >
              第 {chapter.number} 章
            </Typography>
            <Typography
              component="h4"
              variant="h5"
              sx={{
                fontFamily: "var(--font-serif-sc)",
                fontWeight: 600,
                fontSize: { xs: "1.25rem", md: "1.5rem" },
                mt: 1,
                color: "text.primary",
                overflowWrap: "anywhere",
              }}
            >
              {chapter.title}
            </Typography>
          </Box>

          <Divider />

          <Box data-testid="novel-reader-content" sx={{ minWidth: 0 }}>
            {chapter.content ? (
              <MarkdownContent
                variant="article"
                sx={{
                  "& p": {
                    fontFamily: "var(--font-serif-sc) !important",
                    fontSize: "1.125rem !important",
                    lineHeight: "1.8 !important",
                    color: "text.primary",
                    textIndent: "2em",
                    marginBottom: "0.75em",
                    marginTop: 0,
                    textAlign: "justify",
                    overflowWrap: "anywhere",
                  },
                  "& p:first-of-type": {
                    marginTop: "1em",
                  },
                }}
              >
                {chapter.content}
              </MarkdownContent>
            ) : (
              <Alert severity="warning">本章暂无正文内容。</Alert>
            )}
          </Box>
        </Stack>
      </Paper>

      <ReaderNav
        page={currentPage}
        totalPages={totalPages}
        onPrev={() => changePage(currentPage - 1)}
        onNext={() => changePage(currentPage + 1)}
        onPageChange={changePage}
      />
    </Stack>
  );
}
