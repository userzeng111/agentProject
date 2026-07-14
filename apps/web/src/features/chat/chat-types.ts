import type { StoredMessage } from "@/lib/chat-storage";

export interface DisplayMessage extends StoredMessage {
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
