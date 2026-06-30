"use client";

import Markdown, { defaultUrlTransform } from "react-markdown";
import type { Components, UrlTransform } from "react-markdown";
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

/** 判断 src 是否为允许的图片 data URI */
function isSafeImageDataUri(src?: string): boolean {
  if (!src) return false;
  const lower = src.trim().toLowerCase();
  return lower.startsWith("data:") && SAFE_IMAGE_DATA_URI_PREFIXES.some((prefix) => lower.startsWith(prefix));
}

/** 判断是否为外部链接 */
function isExternalLink(href?: string): boolean {
  if (!href) return false;
  return /^https?:\/\//.test(href.trim());
}

const markdownUrlTransform: UrlTransform = (url, key, node) => {
  const tagName = typeof node.tagName === "string" ? node.tagName.toLowerCase() : "";
  if (key === "src" && tagName === "img" && url.trim().toLowerCase().startsWith("data:")) {
    return isSafeImageDataUri(url) ? url : "";
  }
  return defaultUrlTransform(url);
};

/** 安全的链接组件 */
function SafeLink({
  href,
  children,
  node,
  ...rest
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & { node?: unknown }) {
  void node;
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
function SafeImage({
  src,
  alt,
  node,
  ...rest
}: React.ImgHTMLAttributes<HTMLImageElement> & { node?: unknown }) {
  void node;
  if (!isSafeImageSrc(src)) {
    return null;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img {...rest} src={src} alt={alt || ""} />;
}

const inlineCodeSx: SxProps<Theme> = (theme) => {
  const isDark = theme.palette.mode === "dark";
  return {
    px: 0.5,
    py: "1px",
    borderRadius: 0.5,
    bgcolor: isDark ? "rgba(15, 23, 42, 0.72)" : "rgba(15, 23, 42, 0.08)",
    border: "1px solid",
    borderColor: isDark ? "rgba(148, 163, 184, 0.28)" : "rgba(15, 23, 42, 0.12)",
    color: "text.primary",
    fontSize: "0.9em",
    fontFamily: "monospace",
    maxWidth: "100%",
    overflowWrap: "anywhere",
  };
};

function codeBlockSx(compact: boolean): SxProps<Theme> {
  return (theme) => {
    const isDark = theme.palette.mode === "dark";
    return {
      p: compact ? 1.5 : 2,
      my: compact ? 1 : 1.5,
      borderRadius: 1,
      bgcolor: isDark ? "rgba(15, 23, 42, 0.82)" : "rgba(15, 23, 42, 0.06)",
      color: "text.primary",
      border: "1px solid",
      borderColor: isDark ? "rgba(148, 163, 184, 0.24)" : "rgba(15, 23, 42, 0.12)",
      overflowX: "auto",
      maxWidth: "100%",
      minWidth: 0,
      fontSize: compact ? 13 : 14,
      lineHeight: compact ? 1.5 : 1.6,
      fontFamily: "monospace",
      "& code": {
        color: "inherit",
        fontSize: "inherit",
        fontFamily: "inherit",
        whiteSpace: "pre",
      },
    };
  };
}

function InlineCode({ children }: { children: React.ReactNode }) {
  return (
    <Box component="code" sx={inlineCodeSx}>
      {children}
    </Box>
  );
}

function CodeBlock({ children, compact = false }: { children: React.ReactNode; compact?: boolean }) {
  return (
    <Box component="pre" sx={codeBlockSx(compact)}>
      {children}
    </Box>
  );
}

function isBlockCode(className: unknown, children: React.ReactNode): boolean {
  if (typeof className === "string" && className.startsWith("language-")) {
    return true;
  }
  if (typeof children === "string") {
    return children.includes("\n");
  }
  if (Array.isArray(children)) {
    return children.some((child) => typeof child === "string" && child.includes("\n"));
  }
  return false;
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
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
  code: ({ className, children }) => {
    if (isBlockCode(className, children)) {
      return <code className={className}>{children}</code>;
    }
    return <InlineCode>{children}</InlineCode>;
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
  pre: ({ children }) => <CodeBlock compact>{children}</CodeBlock>,
  code: ({ className, children }) => {
    if (isBlockCode(className, children)) {
      return <code className={className}>{children}</code>;
    }
    return <InlineCode>{children}</InlineCode>;
  },
};

/** 根据变体获取组件映射 */
function getComponents(variant: Variant): Components {
  return variant === "article" ? articleComponents : outlineComponents;
}

export default function MarkdownContent({ children, variant = "article", sx }: MarkdownContentProps) {
  return (
    <Box sx={sx}>
      <Markdown components={getComponents(variant)} urlTransform={markdownUrlTransform}>
        {children}
      </Markdown>
    </Box>
  );
}
