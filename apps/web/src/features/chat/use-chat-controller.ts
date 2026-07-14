import { useState, useCallback, useEffect, useRef } from "react";
import type { ModelOption } from "@/lib/types";
import { getModelCatalog, getRagSettings } from "@/lib/api";
import type { StoredMessage } from "@/lib/chat-storage";
import {
  listConversations,
  getConversation,
  saveConversation,
  deleteConversation,
  createConversation,
  getActiveConversationId,
  setActiveConversationId,
} from "@/lib/chat-storage";
import type { DisplayMessage } from "./chat-types";

function restoreMessages(stored: StoredMessage[]): DisplayMessage[] {
  return stored.map((m) => ({
    role: m.role,
    content: m.content,
    reasoning_content: m.reasoning_content,
    tokens: m.tokens,
    createdAt: m.createdAt,
    isStreaming: false,
    isThinking: false,
  }));
}

function serializeMessages(msgs: DisplayMessage[]): StoredMessage[] {
  return msgs.map((m) => ({
    role: m.role,
    content: m.content,
    ...(m.reasoning_content ? { reasoning_content: m.reasoning_content } : {}),
    ...(m.tokens != null ? { tokens: m.tokens } : {}),
    createdAt: Date.now(),
  }));
}

export function useChatController() {
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
  const [validationState, setValidationState] = useState(() => ({
    status: "unverified" as const,
    model_id: "",
  }));

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamingRef = useRef(false);
  const hasInitializedRef = useRef(false);

  // 初始化
  useEffect(() => {
    if (hasInitializedRef.current) return;
    hasInitializedRef.current = true;

    const refreshList = () => setConversationList(listConversations());
    refreshList();

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
    const newConv = createConversation();
    setCurrentConvId(newConv.id);
    setMessages([]);
    setCurrentModel(newConv.model ?? "");
    refreshList();
  }, []);

  // 加载模型目录
  useEffect(() => {
    async function loadModels() {
      try {
        const catalog = await getModelCatalog();
        setModels(catalog.data ?? []);
        setModelCatalogLoaded(true);
      } catch {
        setModels([]);
        setModelCatalogLoaded(false);
      }
    }
    void loadModels();
  }, []);

  // 加载 RAG 状态
  useEffect(() => {
    getRagSettings()
      .then((s) => setRagAvailable(s.available))
      .catch(() => setRagAvailable(false));
  }, []);

  // 切换会话
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
      setCurrentModel(conv.model ?? "");
      setExpandedThinking({});
      setMobileDrawerOpen(false);
    },
    [currentConvId],
  );

  // 新建会话
  const handleNewConversation = useCallback(() => {
    const newConv = createConversation();
    setCurrentConvId(newConv.id);
    setMessages([]);
    setCurrentModel(newConv.model ?? "");
    setExpandedThinking({});
    setConversationList(listConversations());
    setMobileDrawerOpen(false);
  }, []);

  // 删除会话
  const handleDeleteConversation = useCallback(
    (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      deleteConversation(id);
      setConversationList(listConversations());

      if (id === currentConvId) {
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
    },
    [currentConvId],
  );

  // 保存消息到 localStorage
  const persistCurrentMessages = useCallback(
    (msgs: DisplayMessage[]) => {
      if (!currentConvId || streamingRef.current) return;
      const conv = getConversation(currentConvId);
      if (conv) {
        saveConversation({
          ...conv,
          messages: serializeMessages(msgs),
          model: currentModel,
          updatedAt: Date.now(),
        });
        setConversationList(listConversations());
      }
    },
    [currentConvId, currentModel],
  );

  const scrollToBottom = useCallback(() => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 50);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  return {
    // 状态
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
    validationState, setValidationState,
    messagesEndRef,
    streamingRef,
    hasInitializedRef,
    // 操作
    handleSwitchConversation,
    handleNewConversation,
    handleDeleteConversation,
    persistCurrentMessages,
    scrollToBottom,
  };
}
