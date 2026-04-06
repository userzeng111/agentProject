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
  List,
  ListItemButton,
  ListItemText,
  ListItemIcon,
  Divider,
  Button,
  Drawer,
  useMediaQuery,
  useTheme,
  Snackbar,
  Alert,
} from "@mui/material";
import {
  Send as SendIcon,
  Psychology as ThinkIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
  SmartToy as BotIcon,
  Person as UserIcon,
  Add as AddIcon,
  ChatBubbleOutline as ChatIcon,
  Menu as MenuIcon,
} from "@mui/icons-material";
import { streamChat } from "@/lib/api";
import type { ChatStreamChunk, ChatMessage } from "@/lib/types";
import {
  type StoredConversation,
  type StoredMessage,
  listConversations,
  getConversation,
  saveConversation,
  deleteConversation,
  createConversation,
  getActiveConversationId,
  setActiveConversationId,
  buildConversationTitle,
} from "@/lib/chat-storage";

interface DisplayMessage extends ChatMessage {
  reasoning_content?: string;
  isStreaming?: boolean;
  isThinking?: boolean;
  tokens?: number;
}

/** 将持久化消息恢复为显示消息（重设运行时默认值） */
function restoreMessages(stored: StoredMessage[]): DisplayMessage[] {
  return stored.map((m) => ({
    role: m.role,
    content: m.content,
    reasoning_content: m.reasoning_content,
    tokens: m.tokens,
    // 运行时字段重置为默认值
    isStreaming: false,
    isThinking: false,
  }));
}

/** 将显示消息序列化为持久化消息（过滤运行时字段） */
function serializeMessages(msgs: DisplayMessage[]): StoredMessage[] {
  return msgs.map((m) => ({
    role: m.role,
    content: m.content,
    ...(m.reasoning_content ? { reasoning_content: m.reasoning_content } : {}),
    ...(m.tokens != null ? { tokens: m.tokens } : {}),
    createdAt: Date.now(),
  }));
}

/** 格式化时间戳为可读字符串 */
function formatTime(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (isToday) {
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

/** 侧边栏宽度 */
const SIDEBAR_WIDTH = 280;

export function ChatClient() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));

  // ── 会话与消息状态 ──
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [currentConvId, setCurrentConvId] = useState<string | null>(null);
  const [conversationList, setConversationList] = useState<
    Array<{ id: string; title: string; updatedAt: number }>
  >([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [expandedThinking, setExpandedThinking] = useState<Record<number, boolean>>({});
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: "success" | "error" | "info" }>({
    open: false,
    message: "",
    severity: "info",
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 用于标记是否正在流式输出中（避免在流式期间写入 localStorage）
  const streamingRef = useRef(false);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 50);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // ── 初始化：从 localStorage 恢复 ──
  useEffect(() => {
    // 刷新会话列表
    const refreshList = () => setConversationList(listConversations());
    refreshList();

    // 恢复活跃会话
    const activeId = getActiveConversationId();
    if (activeId) {
      const conv = getConversation(activeId);
      if (conv) {
        setCurrentConvId(activeId);
        setMessages(restoreMessages(conv.messages));
        return;
      }
    }
    // 没有活跃会话，自动创建新会话
    const newConv = createConversation();
    setCurrentConvId(newConv.id);
    setMessages([]);
    refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 消息变化后持久化（非流式期间） ──
  useEffect(() => {
    if (!currentConvId || streamingRef.current) return;
    if (messages.length === 0 && currentConvId) {
      // 空消息也要保存（更新时间戳）
      const conv = getConversation(currentConvId);
      if (conv) {
        saveConversation({ ...conv, updatedAt: Date.now() });
      }
      return;
    }
    const conv = getConversation(currentConvId);
    if (!conv) return;
    const serialized = serializeMessages(messages);
    const title = buildConversationTitle(serialized);
    saveConversation({
      ...conv,
      title,
      messages: serialized,
      updatedAt: Date.now(),
    });
    setConversationList(listConversations());
  }, [messages, currentConvId]);

  // ── 显示提示 ──
  const showSnackbar = useCallback((message: string, severity: "success" | "error" | "info" = "info") => {
    setSnackbar({ open: true, message, severity });
  }, []);

  // ── 切换会话 ──
  const handleSwitchConversation = useCallback(
    (id: string) => {
      if (id === currentConvId) {
        setMobileDrawerOpen(false);
        return;
      }
      const conv = getConversation(id);
      if (!conv) return;
      setActiveConversationId(id);
      setCurrentConvId(id);
      setMessages(restoreMessages(conv.messages));
      setExpandedThinking({});
      setMobileDrawerOpen(false);
    },
    [currentConvId],
  );

  // ── 新建会话 ──
  const handleNewConversation = useCallback(() => {
    const newConv = createConversation();
    setCurrentConvId(newConv.id);
    setMessages([]);
    setExpandedThinking({});
    setConversationList(listConversations());
    setMobileDrawerOpen(false);
  }, []);

  // ── 删除会话 ──
  const handleDeleteConversation = useCallback(
    (id: string, e: React.MouseEvent) => {
      e.stopPropagation(); // 阻止触发切换
      deleteConversation(id);
      setConversationList(listConversations());

      if (id === currentConvId) {
        // 删除的是当前会话，切换到最近的或新建
        const remaining = listConversations();
        if (remaining.length > 0) {
          const nextConv = getConversation(remaining[0].id);
          if (nextConv) {
            setActiveConversationId(nextConv.id);
            setCurrentConvId(nextConv.id);
            setMessages(restoreMessages(nextConv.messages));
          }
        } else {
          const newConv = createConversation();
          setCurrentConvId(newConv.id);
          setMessages([]);
          setConversationList(listConversations());
        }
      }
      showSnackbar("会话已删除", "success");
    },
    [currentConvId, showSnackbar],
  );

  // ── 发送消息 ──
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
    streamingRef.current = true;

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
        streamingRef.current = false;
      },
      (msg: string) => {
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          if (lastIdx >= 0 && updated[lastIdx].role === "assistant") {
            updated[lastIdx] = {
              ...updated[lastIdx],
              content: "错误: " + msg,
              isStreaming: false,
              isThinking: false,
            };
          }
          return updated;
        });
        setLoading(false);
        streamingRef.current = false;
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

  // ── 侧边栏会话列表渲染 ──
  const renderSidebarContent = () => (
    <Box
      sx={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        bgcolor: "background.default",
      }}
    >
      {/* 新对话按钮 */}
      <Box sx={{ p: 2 }}>
        <Button
          variant="outlined"
          fullWidth
          startIcon={<AddIcon />}
          onClick={handleNewConversation}
          sx={{
            textTransform: "none",
            borderColor: "primary.main",
            color: "primary.main",
            "&:hover": { borderColor: "primary.dark", bgcolor: "rgba(39,100,81,0.04)" },
          }}
        >
          新对话
        </Button>
      </Box>
      <Divider />

      {/* 会话列表 */}
      <List sx={{ flex: 1, overflowY: "auto", py: 0 }}>
        {conversationList.map((item) => (
          <ListItemButton
            key={item.id}
            selected={item.id === currentConvId}
            onClick={() => handleSwitchConversation(item.id)}
            sx={{
              px: 2,
              py: 1.2,
              "&.Mui-selected": {
                bgcolor: "rgba(39, 100, 81, 0.08)",
                borderLeft: "3px solid",
                borderColor: "primary.main",
              },
              "&.Mui-selected:hover": {
                bgcolor: "rgba(39, 100, 81, 0.12)",
              },
              display: "flex",
              alignItems: "center",
              gap: 1,
            }}
          >
            <ListItemIcon sx={{ minWidth: 32 }}>
              <ChatIcon sx={{ fontSize: 20, color: item.id === currentConvId ? "primary.main" : "text.secondary" }} />
            </ListItemIcon>
            <ListItemText
              primary={item.title}
              secondary={formatTime(item.updatedAt)}
              primaryTypographyProps={{
                noWrap: true,
                fontSize: "0.875rem",
                fontWeight: item.id === currentConvId ? 600 : 400,
              }}
              secondaryTypographyProps={{
                noWrap: true,
                fontSize: "0.7rem",
                color: "text.disabled",
              }}
              sx={{ flex: 1, minWidth: 0 }}
            />
            <Tooltip title="删除会话">
              <IconButton
                size="small"
                onClick={(e) => handleDeleteConversation(item.id, e)}
                sx={{
                  opacity: 0,
                  transition: "opacity 0.2s",
                  ".MuiListItemButton-root:hover &": { opacity: 1 },
                }}
              >
                <DeleteIcon fontSize="small" sx={{ color: "text.secondary", "&:hover": { color: "error.main" } }} />
              </IconButton>
            </Tooltip>
          </ListItemButton>
        ))}
        {conversationList.length === 0 && (
          <Box sx={{ py: 4, textAlign: "center", color: "text.disabled" }}>
            <Typography variant="body2">暂无会话记录</Typography>
          </Box>
        )}
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: "flex", height: "calc(100vh - 64px)" }}>
      {/* ── 侧边栏（桌面端固定，移动端 Drawer） ── */}
      {isMobile ? (
        <Drawer
          open={mobileDrawerOpen}
          onClose={() => setMobileDrawerOpen(false)}
          sx={{ "& .MuiDrawer-paper": { width: SIDEBAR_WIDTH } }}
        >
          {renderSidebarContent()}
        </Drawer>
      ) : (
        <Box
          sx={{
            width: SIDEBAR_WIDTH,
            flexShrink: 0,
            borderRight: "1px solid",
            borderColor: "divider",
            height: "100%",
          }}
        >
          {renderSidebarContent()}
        </Box>
      )}

      {/* ── 主对话区域 ── */}
      <Box
        sx={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minWidth: 0, // 防止 flex 子元素溢出
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
            {/* 移动端菜单按钮 */}
            {isMobile && (
              <IconButton size="small" onClick={() => setMobileDrawerOpen(true)}>
                <MenuIcon />
              </IconButton>
            )}
            <BotIcon sx={{ color: "primary.main", fontSize: 28 }} />
            <Typography variant="h6" sx={{ fontWeight: 600, color: "primary.main" }}>
              AI 对话
            </Typography>
          </Box>
        </Box>

        {/* 消息列表 */}
        <Box
          sx={{
            flex: 1,
            overflowY: "auto",
            px: 2,
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
              <Typography variant="body2">输入消息开始与 AI 对话</Typography>
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
                    <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
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
                    <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
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
                    <Chip size="small" label={`${msg.tokens} tokens`} sx={{ mt: 1, fontSize: "0.7rem" }} />
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
            borderRadius: 0,
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
            {loading ? <CircularProgress size={20} color="inherit" /> : <SendIcon />}
          </IconButton>
        </Paper>
      </Box>

      {/* 提示条 */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={2500}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
          severity={snackbar.severity}
          variant="outlined"
          sx={{ width: "100%" }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
