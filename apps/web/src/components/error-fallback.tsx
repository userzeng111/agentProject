import {
  Box,
  Typography,
  Button,
  Stack,
  Container,
} from "@mui/material";
import { ErrorOutline as ErrorIcon } from "@mui/icons-material";

/**
 * 可复用的错误展示组件。
 *
 * 供 error.tsx 及其他需要展示错误信息的场景使用。
 */

export interface ErrorFallbackProps {
  /** 捕获到的错误对象 */
  error: Error & { digest?: string };
  /** 重试回调 */
  onRetry: () => void;
  /** 可选的自定义标题，默认为"出错了" */
  title?: string;
}

export function ErrorFallback({ error, onRetry, title }: ErrorFallbackProps) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "50vh",
        py: 6,
      }}
    >
      <Container maxWidth="sm">
        <Stack spacing={3} alignItems="center" textAlign="center">
          {/* 错误图标 */}
          <ErrorIcon
            sx={{
              fontSize: 56,
              color: "error.main",
              opacity: 0.8,
            }}
          />

          {/* 标题 */}
          <Typography
            variant="h4"
            sx={{
              fontFamily: "var(--font-serif-sc)",
              fontWeight: 600,
              color: "text.primary",
            }}
          >
            {title ?? "出错了"}
          </Typography>

          {/* 说明 */}
          <Typography color="text.secondary" sx={{ lineHeight: 1.7 }}>
            页面渲染时遇到了问题，请尝试重试。如果问题持续出现，请联系管理员。
          </Typography>

          {/* 错误详情 */}
          {error.message && (
            <Box
              sx={{
                width: "100%",
                px: 2.5,
                py: 1.5,
                background: "error.light",
                borderRadius: 2,
                border: "1px solid rgba(180, 74, 63, 0.12)",
                textAlign: "left",
              }}
            >
              <Typography
                variant="body2"
                sx={{
                  color: "error.main",
                  wordBreak: "break-word",
                  whiteSpace: "pre-wrap",
                  fontFamily: "monospace",
                  fontSize: "0.85rem",
                }}
              >
                {error.message}
              </Typography>
              {error.digest && (
                <Typography
                  variant="caption"
                  sx={{
                    display: "block",
                    mt: 0.5,
                    color: "text.secondary",
                  }}
                >
                  错误追踪码: {error.digest}
                </Typography>
              )}
            </Box>
          )}

          {/* 重试按钮 */}
          <Button
            variant="contained"
            onClick={onRetry}
            sx={{ mt: 1 }}
          >
            重试
          </Button>
        </Stack>
      </Container>
    </Box>
  );
}
