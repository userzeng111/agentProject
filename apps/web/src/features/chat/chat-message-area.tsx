"use client";

import { Box, Button, Chip, Collapse, Stack, Typography } from "@mui/material";
import {
  ExpandMore as ExpandMoreIcon,
  Psychology as ThinkIcon,
  SmartToy as BotIcon,
  Person as UserIcon,
} from "@mui/icons-material";

interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  reasoning_content?: string;
  isStreaming?: boolean;
  isThinking?: boolean;
  tokens?: number;
  validation_meta?: {
    reasoningSignal?: boolean;
    reasoningChars?: number;
    runId?: string;
  };
}

const compactMetadataChipSx = {
  alignSelf: "flex-start",
  width: "fit-content",
  height: "auto",
  maxWidth: "100%",
  fontSize: "0.72rem",
  "& .MuiChip-label": {
    display: "block",
    py: 0.35,
    whiteSpace: "normal",
    overflowWrap: "anywhere",
    wordBreak: "break-word",
    lineHeight: 1.35,
  },
};

export default function ChatMessageArea({
  messages,
  messagesEndRef,
  expandedThinking,
  onToggleThinking,
}: {
  messages: ChatMessage[];
  messagesEndRef?: React.LegacyRef<HTMLDivElement>;
  expandedThinking: Record<number, boolean>;
  onToggleThinking: (index: number) => void;
}) {
  return (
    <Box
      sx={{
        flex: 1,
        overflowY: "auto",
        px: { xs: 1.25, sm: 2 },
        py: 2,
        display: "flex",
        flexDirection: "column",
        gap: 2,
        minWidth: 0,
        minHeight: 0,
        "& > :first-child": { mt: "auto" },
      }}
      role="log"
      aria-live="polite"
      aria-label="聊天消息"
    >
      {messages.map((msg, index) => {
        const isThinkingExpanded = expandedThinking[index] ?? false;
        const thinkingButtonId = `chat-thinking-toggle-${index}`;
        const thinkingContentId = `chat-thinking-content-${index}`;
        const hasMetadata =
          (msg.tokens != null && msg.tokens > 0) ||
          (msg.validation_meta != null && msg.validation_meta.reasoningSignal !== undefined);

        return (
          <Box key={index} sx={{ maxWidth: "100%", alignSelf: msg.role === "user" ? "flex-end" : "flex-start", minWidth: 0 }}>
            <Stack spacing={0.5} sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={0.5} alignItems="center">
              {msg.role === "assistant" ? (
                <BotIcon sx={{ fontSize: 16, color: "primary.main" }} />
              ) : (
                <UserIcon sx={{ fontSize: 16, color: "text.secondary" }} />
              )}
              <Typography variant="caption" color="text.secondary">
                {msg.role === "assistant" ? "AI" : "用户"}
              </Typography>
              {msg.isStreaming && <Chip label="生成中..." size="small" color="info" variant="outlined" sx={{ height: 20 }} />}
            </Stack>

            {/* 思考链 */}
              {msg.reasoning_content ? (
                <Box sx={{ alignSelf: "flex-start", maxWidth: "100%", minWidth: 0 }}>
                  <Button
                    id={thinkingButtonId}
                    type="button"
                    size="small"
                    variant="text"
                    startIcon={<ThinkIcon sx={{ fontSize: 16 }} />}
                    endIcon={
                      <ExpandMoreIcon
                        sx={{
                          fontSize: 18,
                          transform: isThinkingExpanded ? "rotate(180deg)" : "rotate(0deg)",
                          transition: "transform 180ms ease",
                        }}
                      />
                    }
                    aria-expanded={isThinkingExpanded}
                    aria-controls={thinkingContentId}
                    aria-busy={msg.isThinking || undefined}
                    data-testid="chat-thinking-toggle"
                    onClick={() => onToggleThinking(index)}
                    sx={{
                      alignSelf: "flex-start",
                      justifyContent: "flex-start",
                      minWidth: 0,
                      minHeight: { xs: 44, sm: 32 },
                      maxWidth: "100%",
                      px: 1,
                      py: 0.25,
                      borderRadius: 1.25,
                      border: "1px solid",
                      borderColor: "divider",
                      bgcolor: "background.paper",
                      color: "text.secondary",
                      fontSize: "0.75rem",
                      lineHeight: 1.4,
                      "&:hover": { bgcolor: "action.hover" },
                      "&.Mui-focusVisible": {
                        outline: "2px solid",
                        outlineColor: "primary.main",
                        outlineOffset: 2,
                        bgcolor: "action.focus",
                      },
                    }}
                  >
                    {msg.isThinking ? "正在思考" : "思考过程"}
                  </Button>
                  <Collapse in={isThinkingExpanded} timeout={180}>
                    <Box
                      id={thinkingContentId}
                      role="region"
                      aria-labelledby={thinkingButtonId}
                      data-testid="chat-thinking-content"
                      sx={{
                        mt: 0.5,
                        maxWidth: "min(100%, 48rem)",
                        minWidth: 0,
                        p: { xs: 0.75, sm: 1 },
                        border: "1px solid",
                        borderColor: "divider",
                        borderRadius: 1.5,
                        bgcolor: "background.paper",
                      }}
                    >
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{
                          display: "block",
                          fontFamily: "monospace",
                          whiteSpace: "pre-wrap",
                          overflowWrap: "anywhere",
                          wordBreak: "break-word",
                          fontSize: { xs: "0.8125rem", sm: "0.75rem" },
                          lineHeight: 1.6,
                        }}
                      >
                        {msg.reasoning_content}
                      </Typography>
                    </Box>
                  </Collapse>
                </Box>
              ) : null}

            {/* 消息正文 */}
            {msg.content ? (
              <Typography
                variant="body2"
                data-testid="chat-message-content"
                sx={{
                  whiteSpace: "pre-wrap",
                  overflowWrap: "anywhere",
                  wordBreak: "break-word",
                  lineHeight: 1.7,
                  px: 1.5,
                  py: 1,
                  borderRadius: 2,
                  bgcolor: msg.role === "user" ? "primary.main" : "background.paper",
                  color: msg.role === "user" ? "common.white" : "text.primary",
                  border: msg.role === "user" ? "none" : "1px solid",
                  borderColor: msg.role === "user" ? "transparent" : "divider",
                  maxWidth: "100%",
                }}
              >
                {msg.content}
              </Typography>
            ) : null}
              {hasMetadata ? (
                <Box
                  data-testid="chat-message-metadata"
                  sx={{
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "flex-start",
                    alignSelf: "flex-start",
                    gap: 0.5,
                    mt: 0.5,
                    width: "fit-content",
                    maxWidth: "100%",
                    minWidth: 0,
                  }}
                >
                  {msg.tokens != null && msg.tokens > 0 ? (
                    <Chip
                      data-testid="chat-token-usage"
                      size="small"
                      label={`${msg.tokens} tokens`}
                      sx={compactMetadataChipSx}
                    />
                  ) : null}
                  {msg.validation_meta && msg.validation_meta.reasoningSignal !== undefined ? (
                    <Chip
                      data-testid="chat-validation-metadata"
                      size="small"
                      color={msg.validation_meta.reasoningSignal ? "info" : "default"}
                      variant="outlined"
                      label={
                        msg.validation_meta.reasoningSignal
                          ? `推理信号元数据：累计 ${msg.validation_meta.reasoningChars ?? 0} 字符`
                          : "推理信号元数据：暂未收到"
                      }
                      sx={compactMetadataChipSx}
                    />
                  ) : null}
                </Box>
              ) : null}
            </Stack>
          </Box>
        );
      })}
      <div ref={messagesEndRef} />
    </Box>
  );
}
