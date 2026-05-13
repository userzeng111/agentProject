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

/** 危险协议前缀 */
const DANGEROUS_PROTOCOLS = ["javascript:", "data:", "vbscript:"];

/** 安全的图片 data URI MIME 类型前缀 */
const SAFE_IMAGE_DATA_URI_PREFIXES = [
  "data:image/png",
  "data:image/jpeg",
  "data:image/jpg",
  "data:image/gif",
  "data:image/webp",
  "data:image/svg+xml",
  "data:image/bmp",
  "data:image/avif",
];

/** 判断 href 是否包含危险协议 */
function isDangerousHref(href?: string): boolean {
  if (!href) return false;
  const lower = href.trim().toLowerCase();
  return DANGEROUS_PROTOCOLS.some((proto) => lower.startsWith(proto));
}

/** 判断图片 src 是否安全 */
function isSafeImageSrc(src?: string): boolean {
  if (!src) return false;
  const lower = src.trim().toLowerCase();
  // 禁止危险协议（非图片 data URI 的 data: 也在这里被拦截）
  if (DANGEROUS_PROTOCOLS.some((proto) => lower.startsWith(proto))) {
    // 例外：允许已知图片类型的 data URI
    if (lower.startsWith("data:")) {
      return SAFE_IMAGE_DATA_URI_PREFIXES.some((prefix) => lower.startsWith(prefix));
    }
    return false;
  }
  return true;
}

/** 判断是否为外部链接 */
function isExternalLink(href?: string): boolean {
  if (!href) return false;
  return /^https?:\/\//.test(href.trim());
}

/** 安全的链接组件 */
function SafeLink({ href, children, ...rest }: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  if (isDangerousHref(href)) {
    return (
      <a {...rest} href="#" onClick={(e) => e.preventDefault()}>
        {children}
      </a>
    );
  }
  const external = isExternalLink(href);
  return (
    <a
      {...rest}
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
    >
      {children}
    </a>
  );
}

/** 安全的图片组件 */
function SafeImage({ src, alt, ...rest }: React.ImgHTMLAttributes<HTMLImageElement>) {
  if (!isSafeImageSrc(src)) {
    return null;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img {...rest} src={src} alt={alt || ""} />;
}

/** 正文变体的组件映射 */
const articleComponents: Components = {
  a: SafeLink,
  img: SafeImage,
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
  a: SafeLink,
  img: SafeImage,
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
