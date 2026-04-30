function extractErrorMessage(data) {
  if (typeof data === "string" && data.trim()) {
    return data.trim();
  }
  if (data && typeof data === "object") {
    const candidate = data.error ?? data.message ?? data.detail;
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
    if (candidate) {
      return JSON.stringify(candidate);
    }
  }
  return "流式请求失败";
}

export function getStreamChatErrorMessage(error) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }
  return "流式请求网络失败";
}

export function createChatSseParser({ onChunk, onError }) {
  let buffer = "";
  let eventType = "";
  let stopped = false;

  const handleData = (jsonStr) => {
    let data;
    try {
      data = JSON.parse(jsonStr);
    } catch {
      return;
    }

    if (eventType === "chat.error" || data?.error) {
      onError(extractErrorMessage(data));
      stopped = true;
      return;
    }

    if (data.content !== undefined || data.reasoning_content !== undefined) {
      onChunk(data);
    }
    if (data.finish_reason) {
      onChunk(data);
    }
    if (data.usage) {
      onChunk(data);
    }
  };

  const processLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      eventType = "";
      return;
    }
    if (trimmed.startsWith("event:")) {
      eventType = trimmed.slice(6).trim();
      return;
    }
    if (trimmed.startsWith("data:")) {
      handleData(trimmed.slice(5).trim());
    }
  };

  return {
    push(text) {
      if (stopped) return false;
      buffer += text;
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        processLine(line);
        if (stopped) return false;
      }
      return true;
    },
    flush() {
      if (stopped || !buffer.trim()) return !stopped;
      processLine(buffer);
      buffer = "";
      return !stopped;
    },
    get stopped() {
      return stopped;
    },
  };
}
