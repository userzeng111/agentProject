"use client";

import { Box, Chip, Collapse, Stack, Typography } from "@mui/material";
import { Psychology as ThinkIcon, SmartToy as BotIcon, Person as UserIcon } from "@mui/icons-material";

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
      {messages.map((msg, index) => (
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
              <Box>
                <Stack
                  direction="row"
                  spacing={0.5}
                  alignItems="center"
                  onClick={() => onToggleThinking(index)}
                  sx={{ cursor: "pointer", userSelect: "none", py: 0.25 }}
                  role="button"
                  tabIndex={0}
                  aria-expanded={expandedThinking[index] ?? false}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggleThinking(index); } }}
                >
                  <ThinkIcon sx={{ fontSize: 14, color: "text.secondary" }} />
                  <Typography variant="caption" color="text.secondary">
                    {msg.isThinking ? "思考中..." : "思考过程"}
                  </Typography>
                </Stack>
                <Collapse in={expandedThinking[index] ?? false}>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      display: "block",
                      fontFamily: "monospace",
                      whiteSpace: "pre-wrap",
                      fontSize: "0.75rem",
                      lineHeight: 1.6,
                      p: 1,
                      borderRadius: 1,
                      bgcolor: "action.hover",
                    }}
                  >
                    {msg.reasoning_content}
                  </Typography>
                </Collapse>
              </Box>
            ) : null}

            {/* 消息正文 */}
            {msg.content ? (
              <Typography
                variant="body2"
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
            {msg.tokens != null && msg.tokens > 0 && (
              <Chip size="small" label={`${msg.tokens} tokens`} sx={{ mt: 0.5, fontSize: "0.7rem" }} />
            )}
            {msg.validation_meta && msg.validation_meta.reasoningSignal !== undefined ? (
              <Chip
                size="small"
                color={msg.validation_meta.reasoningSignal ? "info" : "default"}
                variant="outlined"
                label={
                  msg.validation_meta.reasoningSignal
                    ? `推理信号元数据：累计 ${msg.validation_meta.reasoningChars ?? 0} 字符`
                    : "推理信号元数据：暂未收到"
                }
                sx={{ mt: 0.5, fontSize: "0.7rem" }}
              />
            ) : null}
          </Stack>
        </Box>
      ))}
      <div ref={messagesEndRef} />
    </Box>
  );
}
