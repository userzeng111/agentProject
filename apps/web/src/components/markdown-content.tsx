"use client";

import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import { Box, Typography, Divider } from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";

/**
 * Markdown 渲染组件
 * - variant="article"：正文大字，适合小说结果页、归档详情页
 * - variant="outline"：大纲紧凑，适合审核页大纲展示
 */

type Variant = "article" | "outline";

interface MarkdownContentProps {
  /** Markdown 源文本 */
  children: string;
  /** 渲染变体 */
  variant?: Variant;
  /** 额外 sx 样式 */
  sx?: SxProps<Theme>;
}

/** 行内 code 样式（避免 Box component="code" 与 react-markdown ref 冲突） */
const inlineCodeStyle: React.CSSProperties = {
  padding: "1px 4px",
  borderRadius: 4,
  backgroundColor: "rgba(0,0,0,0.06)",
  fontSize: "0.9em",
  fontFamily: "monospace",
};

/** 正文变体的组件映射 */
const articleComponents: Components = {
  h1: ({ children }) => (
    <Typography variant="h4" sx={{ mt: 3, mb: 1.5, fontWeight: 700, fontFamily: "var(--font-serif-sc)" }}>
      {children}
    </Typography>
  ),
  h2: ({ children }) => (
    <Typography variant="h5" sx={{ mt: 2.5, mb: 1, fontWeight: 600, fontFamily: "var(--font-serif-sc)" }}>
      {children}
    </Typography>
  ),
  h3: ({ children }) => (
    <Typography variant="h6" sx={{ mt: 2, mb: 0.75, fontWeight: 600 }}>
      {children}
    </Typography>
  ),
  p: ({ children }) => (
    <Typography sx={{ fontSize: 16, lineHeight: 1.85, mb: 1.5, textAlign: "justify" }}>
      {children}
    </Typography>
  ),
  blockquote: ({ children }) => (
    <Box
      sx={{
        borderLeft: 3,
        borderColor: "primary.main",
        pl: 2,
        py: 0.5,
        my: 2,
        bgcolor: "action.hover",
        borderRadius: "0 4px 4px 0",
      }}
    >
      {children}
    </Box>
  ),
  hr: () => <Divider sx={{ my: 3 }} />,
  ul: ({ children }) => (
    <Box component="ul" sx={{ pl: 3, my: 1 }}>
      {children}
    </Box>
  ),
  ol: ({ children }) => (
    <Box component="ol" sx={{ pl: 3, my: 1 }}>
      {children}
    </Box>
  ),
  li: ({ children }) => (
    <Typography component="li" sx={{ fontSize: 16, lineHeight: 1.85, mb: 0.5 }}>
      {children}
    </Typography>
  ),
  strong: ({ children }) => (
    <Box component="strong" sx={{ fontWeight: 700 }}>
      {children}
    </Box>
  ),
  em: ({ children }) => (
    <Box component="em" sx={{ fontStyle: "italic" }}>
      {children}
    </Box>
  ),
  code: ({ className, children, ...rest }) => {
    const isBlock = typeof className === "string" && className.startsWith("language-");
    if (isBlock) {
      return (
        <Box
          component="pre"
          sx={{
            p: 2,
            my: 1.5,
            borderRadius: 1,
            bgcolor: "grey.100",
            overflow: "auto",
            fontSize: 14,
            lineHeight: 1.6,
            fontFamily: "monospace",
          }}
        >
          <code className={className}>{children}</code>
        </Box>
      );
    }
    /* 行内 code 使用原生标签，避免 Box + react-markdown ref 类型冲突 */
    return (
      <code style={inlineCodeStyle} {...rest}>
        {children}
      </code>
    );
  },
};

/** 大纲变体的组件映射（紧凑风格） */
const outlineComponents: Components = {
  h1: ({ children }) => (
    <Typography variant="h6" sx={{ mt: 2, mb: 0.75, fontWeight: 700 }}>
      {children}
    </Typography>
  ),
  h2: ({ children }) => (
    <Typography variant="subtitle1" sx={{ mt: 1.5, mb: 0.5, fontWeight: 600 }}>
      {children}
    </Typography>
  ),
  h3: ({ children }) => (
    <Typography variant="subtitle2" sx={{ mt: 1, mb: 0.25, fontWeight: 600 }}>
      {children}
    </Typography>
  ),
  p: ({ children }) => (
    <Typography sx={{ fontSize: 15, lineHeight: 1.75, mb: 1 }}>
      {children}
    </Typography>
  ),
  blockquote: ({ children }) => (
    <Box
      sx={{
        borderLeft: 3,
        borderColor: "primary.main",
        pl: 2,
        py: 0.5,
        my: 1.5,
        bgcolor: "action.hover",
        borderRadius: "0 4px 4px 0",
      }}
    >
      {children}
    </Box>
  ),
  hr: () => <Divider sx={{ my: 2 }} />,
  ul: ({ children }) => (
    <Box component="ul" sx={{ pl: 2.5, my: 0.5 }}>
      {children}
    </Box>
  ),
  ol: ({ children }) => (
    <Box component="ol" sx={{ pl: 2.5, my: 0.5 }}>
      {children}
    </Box>
  ),
  li: ({ children }) => (
    <Typography component="li" sx={{ fontSize: 15, lineHeight: 1.75, mb: 0.25 }}>
      {children}
    </Typography>
  ),
  strong: ({ children }) => (
    <Box component="strong" sx={{ fontWeight: 700 }}>
      {children}
    </Box>
  ),
  em: ({ children }) => (
    <Box component="em" sx={{ fontStyle: "italic" }}>
      {children}
    </Box>
  ),
  code: ({ className, children, ...rest }) => {
    const isBlock = typeof className === "string" && className.startsWith("language-");
    if (isBlock) {
      return (
        <Box
          component="pre"
          sx={{
            p: 1.5,
            my: 1,
            borderRadius: 1,
            bgcolor: "grey.100",
            overflow: "auto",
            fontSize: 13,
            lineHeight: 1.5,
            fontFamily: "monospace",
          }}
        >
          <code className={className}>{children}</code>
        </Box>
      );
    }
    /* 行内 code 使用原生标签，避免 Box + react-markdown ref 类型冲突 */
    return (
      <code style={inlineCodeStyle} {...rest}>
        {children}
      </code>
    );
  },
};

/** 根据变体获取组件映射 */
function getComponents(variant: Variant): Components {
  return variant === "article" ? articleComponents : outlineComponents;
}

export default function MarkdownContent({ children, variant = "article", sx }: MarkdownContentProps) {
  return (
    <Box sx={sx}>
      <Markdown components={getComponents(variant)}>
        {children}
      </Markdown>
    </Box>
  );
}
