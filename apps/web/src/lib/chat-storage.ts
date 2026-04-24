/**
 * 聊天历史持久化服务
 * 使用 localStorage 存储多会话数据，支持增删改查
 */

/** 持久化消息结构 */
export interface StoredMessage {
  role: "user" | "assistant" | "system";
  content: string;
  reasoning_content?: string;
  tokens?: number;
  createdAt: number;
}

/** 持久化会话结构 */
export interface StoredConversation {
  id: string;
  title: string; // 取首条用户消息前 30 字
  messages: StoredMessage[];
  createdAt: number;
  updatedAt: number;
  model?: string;
}

/** 会话摘要（列表展示用） */
export interface ConversationSummary {
  id: string;
  title: string;
  updatedAt: number;
}

/** localStorage 键名 */
const STORAGE_KEY = "chat_conversations";
const ACTIVE_KEY = "chat_active_conversation";

/** 容量警告阈值：4MB */
const STORAGE_WARNING_BYTES = 4 * 1024 * 1024;

// ── 内部工具函数 ──

/** 读取全部会话原始数据 */
function readAllConversations(): Record<string, StoredConversation> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, StoredConversation>;
  } catch {
    return {};
  }
}

/** 写入全部会话原始数据，带容量保护 */
function writeAllConversations(data: Record<string, StoredConversation>): void {
  if (typeof window === "undefined") return;
  const json = JSON.stringify(data);
  if (json.length > STORAGE_WARNING_BYTES) {
    // 超过 4MB 时弹出提示
    // eslint-disable-next-line no-alert
    console.warn("聊天历史数据已超过 4MB，建议删除部分旧会话以释放空间。");
  }
  try {
    localStorage.setItem(STORAGE_KEY, json);
  } catch (err) {
    if (err instanceof Error && (err.name === "QuotaExceededError" || err.message.toLowerCase().includes("quota"))) {
      console.error("localStorage 存储空间已满，建议删除部分旧会话以释放空间。", err);
      alert("存储空间已满，无法保存聊天历史。请删除部分旧会话后重试。");
    } else {
      console.error("localStorage 写入失败", err);
    }
  }
}

/** 生成唯一会话 ID */
function generateId(): string {
  const suffix = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID().replace(/-/g, "").slice(0, 8)
    : Math.random().toString(36).slice(2, 8);
  return `conv_${Date.now()}_${suffix}`;
}

// ── 对外接口 ──

/** 列出所有会话摘要，按 updatedAt 降序排列 */
export function listConversations(): ConversationSummary[] {
  const all = readAllConversations();
  return Object.values(all)
    .map(({ id, title, updatedAt }) => ({ id, title, updatedAt }))
    .sort((a, b) => b.updatedAt - a.updatedAt);
}

/** 获取某个会话完整数据，不存在则返回 null */
export function getConversation(id: string): StoredConversation | null {
  const all = readAllConversations();
  return all[id] ?? null;
}

/** 保存/更新会话 */
export function saveConversation(conv: StoredConversation): void {
  const all = readAllConversations();
  all[conv.id] = conv;
  writeAllConversations(all);
}

/** 删除某个会话 */
export function deleteConversation(id: string): void {
  const all = readAllConversations();
  delete all[id];
  writeAllConversations(all);

  // 如果删除的是当前活跃会话，清除活跃标记
  if (getActiveConversationId() === id) {
    clearActiveConversationId();
  }
}

/** 创建新会话，返回完整数据（同时设为活跃会话） */
export function createConversation(model?: string): StoredConversation {
  const id = generateId();
  const now = Date.now();
  const conv: StoredConversation = {
    id,
    title: "新对话",
    messages: [],
    createdAt: now,
    updatedAt: now,
    model,
  };
  saveConversation(conv);
  setActiveConversationId(id);
  return conv;
}

// ── 活跃会话 ID 管理 ──

/** 获取当前活跃会话 ID */
export function getActiveConversationId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACTIVE_KEY);
}

/** 设置当前活跃会话 ID */
export function setActiveConversationId(id: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(ACTIVE_KEY, id);
}

/** 清除当前活跃会话 ID */
export function clearActiveConversationId(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACTIVE_KEY);
}

// ── 消息转换工具 ──

/** 从会话标题提取（首条用户消息前 30 字） */
export function buildConversationTitle(messages: StoredMessage[]): string {
  const firstUser = messages.find((m) => m.role === "user");
  if (!firstUser) return "新对话";
  const text = firstUser.content.trim().replace(/\n/g, " ");
  return text.length > 30 ? text.slice(0, 30) + "..." : text;
}
