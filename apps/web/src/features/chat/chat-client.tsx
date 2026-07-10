"use client";

import Link from "next/link";
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
  MenuItem,
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
  Stack,
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
  FactCheck as ValidationIcon,
} from "@mui/icons-material";
import { clearModelValidation, getModelCatalog, getModelValidation, getRagSettings, streamChat, streamModelValidation } from "@/lib/api";
import type { ChatStreamChunk, ChatMessage, ModelOption } from "@/lib/types";
import {
  getModelValidationLabel,
  isGatewayBackedModel,
  resolveChatSelectValue,
  resolveConversationModel,
} from "./model-selection.mjs";
import ModelValidationPanel from "./model-validation-panel";
import {
  applyValidationChatChunkToMessage,
  buildValidationSessionMessages,
  createInitialValidationState,
  parseValidationSearch,
  reduceValidationEvent,
} from "./model-validation-state.mjs";
import {
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
  validation_meta?: {
    reasoningSignal?: boolean;
    reasoningChars?: number;
    runId?: string;
  };
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
const VALIDATION_PANEL_WIDTH = 340;

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
  const [ragAvailable, setRagAvailable] = useState<boolean | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelCatalogLoaded, setModelCatalogLoaded] = useState(false);
  const [currentModel, setCurrentModel] = useState("");
  const [validationPanelOpen, setValidationPanelOpen] = useState(false);
  const [validationState, setValidationState] = useState(() => createInitialValidationState(""));
  const [validationRunning, setValidationRunning] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: "success" | "error" | "info" }>({
    open: false,
    message: "",
    severity: "info",
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 用于标记是否正在流式输出中（避免在流式期间写入 localStorage）
  const streamingRef = useRef(false);
  const activeStreamCountRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const validationAbortControllerRef = useRef<AbortController | null>(null);
  const queryModelRef = useRef("");

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 50);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // ── 初始化：从 localStorage 恢复 ──
  const hasInitializedRef = useRef(false);
  useEffect(() => {
    if (hasInitializedRef.current) return;
    hasInitializedRef.current = true;

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
        setCurrentModel(conv.model ?? "");
        return;
      }
    }
    // 没有活跃会话，自动创建新会话
    const newConv = createConversation();
    setCurrentConvId(newConv.id);
    setMessages([]);
    setCurrentModel(newConv.model ?? "");
    refreshList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const parsed = parseValidationSearch(window.location.search);
    if (parsed.modelId) {
      queryModelRef.current = parsed.modelId;
      setCurrentModel(parsed.modelId);
      setValidationState(createInitialValidationState(parsed.modelId));
    }
    if (parsed.shouldOpen) {
      setValidationPanelOpen(true);
    }
  }, []);

  useEffect(() => {
    async function loadModelCatalog() {
      try {
        const catalog = await getModelCatalog();
        const nextModels = catalog.data ?? [];
        setModels(nextModels);
        setModelCatalogLoaded(true);
      } catch {
        setModels([]);
        setModelCatalogLoaded(false);
      }
    }
    void loadModelCatalog();
  }, []);

  useEffect(() => {
    if (!currentConvId || !modelCatalogLoaded) {
      return;
    }
    const queryModelId = queryModelRef.current;
    if (queryModelId && models.some((item) => item.id === queryModelId && isGatewayBackedModel(item))) {
      queryModelRef.current = "";
      if (currentModel !== queryModelId) {
        setCurrentModel(queryModelId);
      }
      return;
    }
    const conv = getConversation(currentConvId);
    const currentSelection = resolveChatSelectValue(currentModel, models);
    const savedModel = conv?.model || "";
    const nextModel = currentSelection || resolveConversationModel(savedModel, models);
    if (currentModel !== nextModel) {
      setCurrentModel(nextModel);
    }
  }, [currentConvId, currentModel, modelCatalogLoaded, models]);

  useEffect(() => {
    async function loadRagStatus() {
      try {
        const status = await getRagSettings();
        setRagAvailable(Boolean(status.available));
      } catch {
        setRagAvailable(false);
      }
    }
    void loadRagStatus();
  }, []);

  useEffect(() => {
    if (!currentModel) {
      setValidationState(createInitialValidationState(""));
      return;
    }
    let disposed = false;
    const initialState = createInitialValidationState(currentModel);
    setValidationState(initialState);
    void getModelValidation(currentModel)
      .then((report) => {
        if (disposed || !report || report.status === "unverified") {
          return;
        }
        setValidationState(
          reduceValidationEvent(initialState, report.status === "failed"
            ? { type: "validation.error", data: { model_id: currentModel, status: "failed", message: report.failure_reason, report } }
            : { type: "validation.done", data: { model_id: currentModel, status: "verified", report } }),
        );
      })
      .catch(() => {
        // 验证结果读取失败不影响普通聊天。
      });
    return () => {
      disposed = true;
    };
  }, [currentModel]);

  // ── 消息变化后持久化（非流式期间） ──
  useEffect(() => {
    if (!currentConvId || streamingRef.current) return;
    if (messages.length === 0 && currentConvId) {
      // 空消息也要保存（更新时间戳）
      const conv = getConversation(currentConvId);
      if (conv) {
        saveConversation({ ...conv, model: currentModel, updatedAt: Date.now() });
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
      model: currentModel,
      updatedAt: Date.now(),
    });
    setConversationList(listConversations());
  }, [messages, currentConvId, currentModel]);

  // 组件卸载时中止正在进行的请求
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
      validationAbortControllerRef.current?.abort();
    };
  }, []);

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
      setCurrentModel(conv.model || "");
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
    setCurrentModel(newConv.model ?? "");
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
            setCurrentModel(nextConv.model || "");
          }
        } else {
          const newConv = createConversation();
          setCurrentConvId(newConv.id);
          setMessages([]);
          setCurrentModel(newConv.model ?? "");
          setConversationList(listConversations());
        }
      }
      showSnackbar("会话已删除", "success");
    },
    [currentConvId, showSnackbar],
  );

  const selectableModels = models.filter((item) => isGatewayBackedModel(item));
  const chatSelectValue = resolveChatSelectValue(currentModel, selectableModels);
  const selectedModel = selectableModels.find((item) => item.id === chatSelectValue) ?? null;
  const chatModelMenuItems = selectableModels.length
    ? [
        <MenuItem key="empty-model" value="" disabled>
          <em>请选择聊天模型</em>
        </MenuItem>,
        ...selectableModels.map((item) => (
          <MenuItem key={item.id} value={item.id}>
            <Stack spacing={0.25} sx={{ minWidth: 0 }}>
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 500,
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {item.display_name || item.id}
              </Typography>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {getModelValidationLabel(item)}
                {item.provider ? ` · ${item.provider}` : ""}
              </Typography>
            </Stack>
          </MenuItem>
        )),
      ]
    : [
        <MenuItem key="no-model" value="" disabled>
          暂无可用模型
        </MenuItem>,
      ];

  const beginStreaming = useCallback(() => {
    activeStreamCountRef.current += 1;
    streamingRef.current = true;
  }, []);

  const endStreaming = useCallback(() => {
    activeStreamCountRef.current = Math.max(0, activeStreamCountRef.current - 1);
    streamingRef.current = activeStreamCountRef.current > 0;
  }, []);

  // ── 发送消息 ──
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading || !chatSelectValue) return;

    abortControllerRef.current?.abort();
    validationAbortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();

    const userMsg: DisplayMessage = { role: "user", content: text };
    const assistantMsg: DisplayMessage = {
      role: "assistant",
      content: "",
      reasoning_content: "",
      isStreaming: true,
      isThinking: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setLoading(true);
    beginStreaming();

    const apiMessages = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    let contentAccum = "";
    let reasoningAccum = "";
    let totalTokens = 0;

    await streamChat(
      apiMessages,
      chatSelectValue,
      Boolean(ragAvailable),
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
        endStreaming();
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
        endStreaming();
      },
      abortControllerRef.current?.signal,
    );
  }, [beginStreaming, chatSelectValue, endStreaming, input, loading, messages, ragAvailable]);

  const refreshModelCatalog = useCallback(async (refresh = true) => {
    const catalog = await getModelCatalog({ refresh });
    const nextModels = catalog.data ?? [];
    setModels(nextModels);
    setModelCatalogLoaded(true);
  }, []);

  const updateValidationAssistant = useCallback((runId: string, update: (message: DisplayMessage) => DisplayMessage) => {
    setMessages((prev) => {
      const updated = [...prev];
      for (let idx = updated.length - 1; idx >= 0; idx -= 1) {
        const message = updated[idx];
        if (message.role === "assistant" && message.validation_meta?.runId === runId) {
          updated[idx] = update(message);
          break;
        }
      }
      return updated;
    });
  }, []);

  const handleRunValidation = useCallback(async () => {
    const modelId = currentModel || chatSelectValue;
    if (!modelId || validationRunning) {
      return;
    }

    abortControllerRef.current?.abort();
    validationAbortControllerRef.current?.abort();
    const controller = new AbortController();
    validationAbortControllerRef.current = controller;
    const runId =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `validation-${Date.now()}`;
    const [userMsg, assistantMsg] = buildValidationSessionMessages(modelId, runId) as DisplayMessage[];

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setValidationState(createInitialValidationState(modelId));
    setValidationPanelOpen(true);
    setValidationRunning(true);
    beginStreaming();

    try {
      await streamModelValidation(
        modelId,
        {
          onEvent: (event) => {
            setValidationState((prev) => reduceValidationEvent(prev, event));
            if (event.type === "validation.chat_chunk") {
              updateValidationAssistant(runId, (message) =>
                applyValidationChatChunkToMessage(message, event.data) as DisplayMessage,
              );
            }
            if (event.type === "validation.done" || event.type === "validation.error") {
              updateValidationAssistant(runId, (message) => ({ ...message, isStreaming: false, isThinking: false }));
            }
            if (event.type === "validation.done") {
              void refreshModelCatalog(true);
            }
          },
          onError: (message) => {
            setValidationState((prev) =>
              reduceValidationEvent(prev, {
                type: "validation.error",
                data: { model_id: modelId, status: "failed", message },
              }),
            );
            updateValidationAssistant(runId, (assistant) => ({
              ...assistant,
              content: assistant.content || `错误: ${message}`,
              isStreaming: false,
              isThinking: false,
            }));
          },
        },
        controller.signal,
      );
    } finally {
      setValidationRunning(false);
      endStreaming();
      updateValidationAssistant(runId, (message) => ({ ...message, isStreaming: false, isThinking: false }));
    }
  }, [beginStreaming, chatSelectValue, currentModel, endStreaming, refreshModelCatalog, updateValidationAssistant, validationRunning]);

  const handleCancelValidation = useCallback(() => {
    validationAbortControllerRef.current?.abort();
    validationAbortControllerRef.current = null;
    setValidationRunning(false);
    setMessages((prev) =>
      prev.map((message) =>
        message.role === "assistant" && message.validation_meta
          ? { ...message, isStreaming: false, isThinking: false }
          : message,
      ),
    );
    setValidationState((prev) =>
      reduceValidationEvent(prev, { type: "validation.cancelled", data: { message: "用户取消验证" } }),
    );
  }, []);

  const handleClearValidation = useCallback(async () => {
    const modelId = currentModel || chatSelectValue;
    if (!modelId || validationRunning) {
      return;
    }
    try {
      const report = await clearModelValidation(modelId);
      setValidationState(createInitialValidationState(modelId));
      if (report?.status === "unverified") {
        await refreshModelCatalog(true);
      }
      showSnackbar("验证记录已清除", "success");
    } catch (err) {
      showSnackbar(err instanceof Error ? err.message : "清除验证记录失败", "error");
    }
  }, [chatSelectValue, currentModel, refreshModelCatalog, showSnackbar, validationRunning]);

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

  const handleModelChange = useCallback(
    (modelId: string) => {
      setCurrentModel(modelId);
      if (!currentConvId) {
        return;
      }
      const conv = getConversation(currentConvId);
      if (!conv) {
        return;
      }
      saveConversation({ ...conv, model: modelId, updatedAt: Date.now() });
      setConversationList(listConversations());
    },
    [currentConvId],
  );

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
            alignItems: { xs: "stretch", sm: "center" },
            justifyContent: "space-between",
            flexWrap: { xs: "wrap", sm: "nowrap" },
            gap: { xs: 1, sm: 2 },
            px: { xs: 1.25, sm: 2 },
            py: { xs: 1, sm: 1.5 },
            borderBottom: "1px solid",
            borderColor: "divider",
            minWidth: 0,
          }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              minWidth: 0,
              flex: { xs: "1 1 auto", sm: "0 1 auto" },
            }}
          >
            {/* 移动端菜单按钮 */}
            {isMobile && (
              <IconButton size="small" aria-label="打开会话列表" onClick={() => setMobileDrawerOpen(true)}>
                <MenuIcon />
              </IconButton>
            )}
            <BotIcon sx={{ color: "primary.main", display: { xs: "none", sm: "block" }, fontSize: 28 }} />
            <Typography
              variant="h6"
              noWrap
              sx={{
                fontWeight: 600,
                color: "primary.main",
                fontSize: { xs: "1rem", sm: "1.25rem" },
                minWidth: 0,
              }}
            >
              AI 对话
            </Typography>
          </Box>
          <Stack
            direction="row"
            spacing={1}
            alignItems="flex-start"
            sx={{
              flex: { xs: "1 0 100%", sm: "0 0 auto" },
              width: { xs: "100%", sm: "auto" },
              minWidth: 0,
            }}
          >
            {isMobile ? (
              <Button
                size="small"
                variant="outlined"
                startIcon={<ValidationIcon />}
                onClick={() => setValidationPanelOpen(true)}
                sx={{ minHeight: 40, flexShrink: 0 }}
              >
                验证
              </Button>
            ) : null}
            <TextField
              select
              size="small"
              label="聊天模型"
              value={chatSelectValue}
              onChange={(event) => handleModelChange(event.target.value)}
              sx={{
                flex: { xs: 1, sm: "0 0 220px" },
                minWidth: 0,
                width: { xs: "auto", sm: 220 },
              }}
              helperText={chatSelectValue ? "当前会话已显式选择模型" : "请选择当前在线模型后再发送消息"}
              SelectProps={{
                displayEmpty: true,
                renderValue: (value) => (value ? String(value) : <em>请选择聊天模型</em>),
                MenuProps: {
                  PaperProps: {
                    "data-testid": "chat-model-menu",
                    sx: {
                      maxHeight: "min(52vh, 420px)",
                      width: { xs: "calc(100vw - 32px)", sm: 320 },
                      maxWidth: "calc(100vw - 32px)",
                      overflowY: "auto",
                      overscrollBehavior: "contain",
                    },
                  },
                  MenuListProps: {
                    sx: { py: 0.5 },
                  },
                },
              }}
              FormHelperTextProps={{
                sx: {
                  overflowWrap: "anywhere",
                  wordBreak: "break-word",
                },
              }}
            >
              {chatModelMenuItems}
            </TextField>
          </Stack>
        </Box>

        {ragAvailable === false ? (
          <Alert severity="info" sx={{ mx: 2, mt: 2 }}>
            当前小说知识库未构建，本页仍可继续对话，但不会使用小说 RAG。请先前往
            {" "}
            <Link href="/settings">设置页</Link>
            {" "}
            完成索引构建。
          </Alert>
        ) : null}

        {/* 消息列表 */}
        <Box
          sx={(theme) => ({
            flex: 1,
            overflowY: "auto",
            overflowX: "hidden",
            minWidth: 0,
            px: 2,
            py: 1,
            "&::-webkit-scrollbar": { width: 6 },
            "&::-webkit-scrollbar-thumb": {
              backgroundColor:
                theme.palette.mode === "dark"
                  ? "rgba(242, 238, 232, 0.22)"
                  : "rgba(0,0,0,0.15)",
              borderRadius: 3,
            },
          })}
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
              key={`${msg.role}-${msg.content.slice(0, 20)}-${idx}`}
              sx={{
                display: "flex",
                justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                mb: 1.5,
                minWidth: 0,
              }}
            >
              {msg.role === "user" ? (
                <Paper
                  elevation={0}
                  sx={{
                    px: 2,
                    py: 1.5,
                    maxWidth: { xs: "100%", sm: "75%" },
                    minWidth: 0,
                    bgcolor: "rgba(39, 100, 81, 0.06)",
                    border: "1px solid rgba(39, 100, 81, 0.12)",
                    borderRadius: 2,
                    overflowWrap: "anywhere",
                  }}
                >
                  <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1, minWidth: 0 }}>
                    <UserIcon sx={{ fontSize: 20, color: "primary.main", mt: 0.5 }} />
                    <Typography
                      variant="body2"
                      sx={{
                        minWidth: 0,
                        whiteSpace: "pre-wrap",
                        lineHeight: 1.6,
                        overflowWrap: "anywhere",
                        wordBreak: "break-word",
                      }}
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
                    maxWidth: { xs: "100%", sm: "85%" },
                    minWidth: 0,
                    bgcolor: "background.paper",
                    border: "1px solid",
                    borderColor: "divider",
                    borderRadius: 2,
                    overflowWrap: "anywhere",
                  }}
                >
                  {/* 思考链区域 */}
                  {msg.reasoning_content && (
                    <Box sx={{ mb: 1 }}>
                      <Box
                        component="button"
                        type="button"
                        aria-expanded={Boolean(expandedThinking[idx])}
                        aria-controls={`thinking-content-${idx}`}
                        onClick={() => toggleThinking(idx)}
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          gap: 0.5,
                          cursor: "pointer",
                          color: "text.secondary",
                          border: 0,
                          p: 0,
                          bgcolor: "transparent",
                          font: "inherit",
                          textAlign: "left",
                          borderRadius: 1,
                          "&:hover": { color: "primary.main" },
                          "&:focus-visible": {
                            outline: "2px solid",
                            outlineColor: "primary.main",
                            outlineOffset: 2,
                          },
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
                          id={`thinking-content-${idx}`}
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
                            overflowWrap: "anywhere",
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
                  <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1, minWidth: 0 }}>
                    <BotIcon sx={{ fontSize: 20, color: "primary.main", mt: 0.5 }} />
                    <Typography
                      variant="body2"
                      sx={{
                        minWidth: 0,
                        whiteSpace: "pre-wrap",
                        lineHeight: 1.6,
                        overflowWrap: "anywhere",
                        wordBreak: "break-word",
                      }}
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
                    <Chip size="small" label={`${msg.tokens} tokens`} sx={{ mt: 1, fontSize: "0.7rem" }} />
                  )}
                  {msg.validation_meta ? (
                    <Box sx={{ mt: 1 }}>
                      <Chip
                        size="small"
                        color={msg.validation_meta.reasoningSignal ? "info" : "default"}
                        variant="outlined"
                        label={
                          msg.validation_meta.reasoningSignal
                            ? `推理信号元数据：累计 ${msg.validation_meta.reasoningChars ?? 0} 字符`
                            : "推理信号元数据：暂未收到"
                        }
                        sx={{ fontSize: "0.7rem" }}
                      />
                    </Box>
                  ) : null}
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
            aria-label="发送消息"
            color="primary"
            onClick={handleSend}
            disabled={!input.trim() || loading || !chatSelectValue}
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

      {isMobile ? (
        <Drawer
          anchor="right"
          open={validationPanelOpen}
          onClose={() => setValidationPanelOpen(false)}
          sx={{ "& .MuiDrawer-paper": { width: "min(100vw, 360px)", p: 1.5 } }}
        >
          <ModelValidationPanel
            model={selectedModel}
            state={validationState}
            running={validationRunning}
            onRun={handleRunValidation}
            onClear={handleClearValidation}
            onCancel={handleCancelValidation}
          />
        </Drawer>
      ) : (
        <Box
          sx={{
            width: VALIDATION_PANEL_WIDTH,
            flexShrink: 0,
            borderLeft: "1px solid",
            borderColor: "divider",
            p: 1.5,
            height: "100%",
          }}
        >
          <ModelValidationPanel
            model={selectedModel}
            state={validationState}
            running={validationRunning}
            onRun={handleRunValidation}
            onClear={handleClearValidation}
            onCancel={handleCancelValidation}
          />
        </Box>
      )}

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
