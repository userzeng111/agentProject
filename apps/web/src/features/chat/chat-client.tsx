"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  Box,
  Paper,
  TextField,
  IconButton,
  Typography,
  Collapse,
  CircularProgress,
  Chip,
  Tooltip,
} from "@mui/material";
import {
  Send as SendIcon,
  Psychology as ThinkIcon,
  Delete as ClearIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
  SmartToy as BotIcon,
  Person as UserIcon,
} from "@mui/icons-material";
import { streamChat } from "@/lib/api";
import type { ChatStreamChunk, ChatMessage } from "@/lib/types";

interface DisplayMessage extends ChatMessage {
  reasoning_content?: string;
  isStreaming?: boolean;
  isThinking?: boolean;
  tokens?: number;
}

export function ChatClient() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [expandedThinking, setExpandedThinking] = useState<Record<number, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 50);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: DisplayMessage = { role: "user", content: text };
    const assistantMsg: DisplayMessage = {
      role: "assistant",
      content: "",
      reasoning_content: "",
      isStreaming: true,
      isThinking: true,
    };

    const newMessages = [...messages, userMsg, assistantMsg];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    const apiMessages = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    let contentAccum = "";
    let reasoningAccum = "";
    let totalTokens = 0;

    await streamChat(
      apiMessages,
      undefined,
      (chunk: ChatStreamChunk) => {
        if (chunk.reasoning_content) {
          reasoningAccum += chunk.reasoning_content;
        }
        if (chunk.content) {
          contentAccum += chunk.content;
        }
        if (chunk.usage) {
          totalTokens = chunk.usage.total_tokens ?? 0;
        }
        const isStillThinking = !chunk.content && !!chunk.reasoning_content;

        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = {
              ...updated[lastIdx],
              content: contentAccum,
              reasoning_content: reasoningAccum || undefined,
              isStreaming: !chunk.finish_reason,
              isThinking: isStillThinking && !chunk.finish_reason,
              tokens: totalTokens,
            };
          }
          return updated;
        });
      },
      () => {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = {
              ...updated[lastIdx],
              isStreaming: false,
              isThinking: false,
            };
          }
          return updated;
        });
        setLoading(false);
      },
      (msg: string) => {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = {
              ...updated[lastIdx],
              content: "\u9519\u8bef: " + msg,
              isStreaming: false,
              isThinking: false,
            };
          }
          return updated;
        });
        setLoading(false);
      },
    );
  }, [input, loading, messages, scrollToBottom]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const toggleThinking = useCallback((idx: number) => {
    setExpandedThinking((prev) => ({ ...prev, [idx]: !prev[idx] }));
  }, []);

  const clearChat = useCallback(() => {
    setMessages([]);
  }, []);

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        height: "calc(100vh - 64px)",
        maxWidth: 860,
        mx: "auto",
        px: 2,
      }}
    >
      {/* 标题栏 */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1.5,
          borderBottom: "1px solid",
          borderColor: "divider",
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <BotIcon sx={{ color: "primary.main", fontSize: 28 }} />
          <Typography variant="h6" sx={{ fontWeight: 600, color: "primary.main" }}>
            AI 对话
          </Typography>
        </Box>
        <Tooltip title="清空对话">
          <span>
            <IconButton
              size="small"
              onClick={clearChat}
              disabled={messages.length === 0 || loading}
            >
              <ClearIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {/* 消息列表 */}
      <Box
        sx={{
          flex: 1,
          overflowY: "auto",
          px: 1,
          py: 1,
          "&::-webkit-scrollbar": { width: 6 },
          "&::-webkit-scrollbar-thumb": {
            backgroundColor: "rgba(0,0,0,0.15)",
            borderRadius: 3,
          },
        }}
      >
        {messages.length === 0 && (
          <Box
            sx={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              color: "text.disabled",
              gap: 1,
            }}
          >
            <BotIcon sx={{ fontSize: 48, opacity: 0.3 }} />
            <Typography variant="body2">
              输入消息开始与 AI 对话
            </Typography>
          </Box>
        )}

        {messages.map((msg, idx) => (
          <Box
            key={idx}
            sx={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              mb: 1.5,
            }}
          >
            {msg.role === "user" ? (
              <Paper
                elevation={0}
                sx={{
                  px: 2,
                  py: 1.5,
                  maxWidth: "75%",
                  bgcolor: "rgba(39, 100, 81, 0.06)",
                  border: "1px solid rgba(39, 100, 81, 0.12)",
                  borderRadius: 2,
                }}
              >
                <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1 }}>
                  <UserIcon sx={{ fontSize: 20, color: "primary.main", mt: 0.5 }} />
                  <Typography
                    variant="body2"
                    sx={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}
                  >
                    {msg.content}
                  </Typography>
                </Box>
              </Paper>
            ) : (
              <Paper
                elevation={0}
                sx={{
                  px: 2,
                  py: 1.5,
                  maxWidth: "85%",
                  bgcolor: "background.paper",
                  border: "1px solid",
                  borderColor: "divider",
                  borderRadius: 2,
                }}
              >
                {/* 思考链区域 */}
                {msg.reasoning_content && (
                  <Box sx={{ mb: 1 }}>
                    <Box
                      onClick={() => toggleThinking(idx)}
                      sx={{
                        display: "flex",
                        alignItems: "center",
                        gap: 0.5,
                        cursor: "pointer",
                        color: "text.secondary",
                        "&:hover": { color: "primary.main" },
                        userSelect: "none",
                      }}
                    >
                      <ThinkIcon
                        sx={{
                          fontSize: 18,
                          color: msg.isThinking ? "primary.main" : "text.secondary",
                        }}
                      />
                      <Box
                        component="span"
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          gap: 0.5,
                          fontSize: "0.75rem",
                        }}
                      >
                        {msg.isThinking ? "正在思考..." : "思考过程"}
                        {msg.isThinking ? (
                          <CircularProgress size={12} sx={{ ml: 0.5 }} />
                        ) : expandedThinking[idx] ? (
                          <CollapseIcon sx={{ fontSize: 16 }} />
                        ) : (
                          <ExpandIcon sx={{ fontSize: 16 }} />
                        )}
                      </Box>
                    </Box>
                    <Collapse in={expandedThinking[idx] ?? false}>
                      <Box
                        sx={{
                          pl: 1.5,
                          py: 1,
                          bgcolor: "rgba(39, 100, 81, 0.03)",
                          borderRadius: 1,
                          border: "1px dashed rgba(39, 100, 81, 0.1)",
                          maxHeight: 300,
                          overflowY: "auto",
                          fontSize: "0.85rem",
                          color: "text.secondary",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          lineHeight: 1.6,
                          fontFamily: "monospace",
                        }}
                      >
                        {msg.reasoning_content}
                        {msg.isStreaming && (
                          <Box
                            component="span"
                            sx={{
                              display: "inline-block",
                              width: 6,
                              height: 14,
                              bgcolor: "primary.main",
                              borderRadius: "3px",
                              animation: "pulse 1.2s infinite",
                              "@keyframes pulse": {
                                "0%": { opacity: 1 },
                                "100%": { opacity: 0.3 },
                              },
                            }}
                          />
                        )}
                      </Box>
                    </Collapse>
                  </Box>
                )}
                {/* 正式回复内容 */}
                <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1 }}>
                  <BotIcon sx={{ fontSize: 20, color: "primary.main", mt: 0.5 }} />
                  <Typography
                    variant="body2"
                    sx={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}
                  >
                    {msg.content}
                    {msg.isStreaming && (
                      <Box
                        component="span"
                        sx={{
                          display: "inline-block",
                          width: 6,
                          height: 14,
                          bgcolor: "primary.main",
                          borderRadius: "3px",
                          animation: "pulse 1.2s infinite",
                          "@keyframes pulse": {
                            "0%": { opacity: 1 },
                            "100%": { opacity: 0.3 },
                          },
                        }}
                      />
                    )}
                  </Typography>
                </Box>
                {msg.tokens != null && msg.tokens > 0 && (
                  <Chip
                    size="small"
                    label={`${msg.tokens} tokens`}
                    sx={{ mt: 1, fontSize: "0.7rem" }}
                  />
                )}
              </Paper>
            )}
          </Box>
        ))}
        <div ref={messagesEndRef} />
      </Box>

      {/* 输入区域 */}
      <Paper
        elevation={0}
        sx={{
          px: 2,
          py: 1,
          display: "flex",
          alignItems: "flex-end",
          gap: 1,
          borderTop: "1px solid",
          borderColor: "divider",
          borderRadius: 2,
        }}
      >
        <TextField
          fullWidth
          multiline
          minRows={1}
          maxRows={4}
          placeholder="输入消息，按回车发送..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
          size="small"
          sx={{
            flex: 1,
            "& .MuiOutlinedInput-root": {
              borderRadius: 2,
            },
          }}
        />
        <IconButton
          color="primary"
          onClick={handleSend}
          disabled={!input.trim() || loading}
          sx={{
            bgcolor: "primary.main",
            color: "white",
            borderRadius: 2,
            "&:hover": { bgcolor: "primary.dark" },
            "&:disabled": { bgcolor: "action.disabledBackground" },
          }}
        >
          {loading ? (
            <CircularProgress size={20} color="inherit" />
          ) : (
            <SendIcon />
          )}
        </IconButton>
      </Paper>
    </Box>
  );
}
