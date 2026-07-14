"use client";

import Link from "next/link";
import { useState, useRef, useCallback, useEffect } from "react";
import {
  Box,
  TextField,
  IconButton,
  Typography,
  MenuItem,
  Button,
  Drawer,
  useMediaQuery,
  useTheme,
  Snackbar,
  Alert,
  Stack,
} from "@mui/material";
import {
  SmartToy as BotIcon,
  Menu as MenuIcon,
  FactCheck as ValidationIcon,
} from "@mui/icons-material";
import { clearModelValidation, getModelCatalog, getModelValidation, getRagSettings, streamChat, streamModelValidation } from "@/lib/api";
import type { ChatStreamChunk } from "@/lib/types";
import {
  getModelValidationLabel,
  isGatewayBackedModel,
  resolveChatSelectValue,
  resolveConversationModel,
} from "./model-selection.mjs";
import ModelValidationPanel from "./model-validation-panel";
import ChatSessionSidebar from "./chat-session-sidebar";
import ChatMessageArea from "./chat-message-area";
import ChatInputArea from "./chat-input-area";
import type { DisplayMessage } from "./chat-types";
import { useChatController } from "./use-chat-controller";
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
  buildConversationTitle,
} from "@/lib/chat-storage";


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

/** 侧边栏宽度 */
const SIDEBAR_WIDTH = 280;
const VALIDATION_PANEL_WIDTH = 340;

export function ChatClient() {
  const theme = useTheme();
  const isSmallDrawer = useMediaQuery(theme.breakpoints.down("md"));
  const isDesktop = useMediaQuery(theme.breakpoints.up("lg"));

  // ── 控制器层（状态 + 会话管理） ──
  const ctrl = useChatController();
  const {
    messages, setMessages,
    currentConvId,
    conversationList, setConversationList,
    input, setInput,
    loading, setLoading,
    expandedThinking, setExpandedThinking,
    mobileDrawerOpen, setMobileDrawerOpen,
    ragAvailable, setRagAvailable,
    models, setModels,
    modelCatalogLoaded, setModelCatalogLoaded,
    currentModel, setCurrentModel,
    validationPanelOpen, setValidationPanelOpen,
    messagesEndRef,
    streamingRef,
    handleSwitchConversation,
    handleNewConversation,
    handleDeleteConversation,
    scrollToBottom,
  } = ctrl;

  // ChatClient 独有状态
  const [validationState, setValidationState] = useState(() => createInitialValidationState(""));
  const [validationRunning, setValidationRunning] = useState(false);
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: "success" | "error" | "info" }>({
    open: false,
    message: "",
    severity: "info",
  });

  const activeStreamCountRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const validationAbortControllerRef = useRef<AbortController | null>(null);
  const queryModelRef = useRef("");

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

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
  }, [setCurrentModel, setValidationPanelOpen]);

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
  }, [setModelCatalogLoaded, setModels]);

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
  }, [currentConvId, currentModel, modelCatalogLoaded, models, setCurrentModel]);

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
  }, [setRagAvailable]);

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
  }, [currentConvId, currentModel, messages, setConversationList, streamingRef]);

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
  }, [streamingRef]);

  const endStreaming = useCallback(() => {
    activeStreamCountRef.current = Math.max(0, activeStreamCountRef.current - 1);
    streamingRef.current = activeStreamCountRef.current > 0;
  }, [streamingRef]);

  // ── 发送消息 ──
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading || !chatSelectValue) return;

    abortControllerRef.current?.abort();
    validationAbortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();

    const userMsg: DisplayMessage = { role: "user", content: text, createdAt: Date.now() };
    const assistantMsg: DisplayMessage = {
      role: "assistant",
      content: "",
      reasoning_content: "",
      isStreaming: true,
      isThinking: true,
      createdAt: Date.now(),
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
  }, [
    beginStreaming,
    chatSelectValue,
    endStreaming,
    input,
    loading,
    messages,
    ragAvailable,
    setInput,
    setLoading,
    setMessages,
  ]);

  const refreshModelCatalog = useCallback(async (refresh = true) => {
    const catalog = await getModelCatalog({ refresh });
    const nextModels = catalog.data ?? [];
    setModels(nextModels);
    setModelCatalogLoaded(true);
  }, [setModelCatalogLoaded, setModels]);

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
  }, [setMessages]);

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
  }, [
    beginStreaming,
    chatSelectValue,
    currentModel,
    endStreaming,
    refreshModelCatalog,
    setMessages,
    setValidationPanelOpen,
    updateValidationAssistant,
    validationRunning,
  ]);

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
  }, [setMessages]);

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
    [currentConvId, setConversationList, setCurrentModel],
  );

  // ── 侧边栏会话列表渲染 ──
  const renderSidebarContent = () => (
    <ChatSessionSidebar
      conversations={conversationList}
      currentConvId={currentConvId}
      onSelectConversation={handleSwitchConversation}
      onNewConversation={handleNewConversation}
      onDeleteConversation={(id) => handleDeleteConversation(id, { stopPropagation: () => {} } as React.MouseEvent)}
    />
  );

  return (
    <Box sx={{ display: "flex", height: "calc(100vh - 64px)" }}>
      {/* ── 侧边栏（桌面端固定，小屏 Drawer） ── */}
      {isSmallDrawer ? (
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
            {/* 小屏菜单按钮 */}
            {isSmallDrawer && (
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
            {!isDesktop ? (
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

        {/* 消息列表 + 输入区域 */}
        <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
          {messages.length === 0 && (
            <Box sx={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", color: "text.disabled", gap: 1 }}>
              <BotIcon sx={{ fontSize: 48, opacity: 0.3 }} />
              <Typography variant="body2">输入消息开始与 AI 对话</Typography>
            </Box>
          )}
          {messages.length > 0 && (
            <ChatMessageArea
              messages={messages}
              messagesEndRef={messagesEndRef}
              expandedThinking={expandedThinking}
              onToggleThinking={(idx) => setExpandedThinking((prev) => ({ ...prev, [idx]: !prev[idx] }))}
            />
          )}
          <ChatInputArea
            value={input}
            onChange={setInput}
            onSend={handleSend}
            loading={loading}
            canSend={Boolean(chatSelectValue)}
          />
          </Box>
        </Box>

      {isDesktop ? (
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
      ) : (
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
