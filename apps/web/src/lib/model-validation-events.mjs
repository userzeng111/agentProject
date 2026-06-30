const VALIDATION_EVENT_PREFIX = "validation.";

function parseValidationEvent(eventType, jsonText) {
  const type = eventType && eventType.startsWith(VALIDATION_EVENT_PREFIX) ? eventType : "validation.message";
  return {
    type,
    data: JSON.parse(jsonText),
  };
}

export function createModelValidationSseParser({ onEvent, onError }) {
  let buffer = "";

  const processFrame = (frame) => {
    const lines = frame.split(/\r?\n/);
    let eventType = "";
    const dataLines = [];

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith(":")) {
        continue;
      }
      if (trimmed.startsWith("event:")) {
        eventType = trimmed.slice(6).trim();
        continue;
      }
      if (trimmed.startsWith("data:")) {
        dataLines.push(trimmed.slice(5).trim());
      }
    }

    if (!dataLines.length) {
      return;
    }

    try {
      onEvent(parseValidationEvent(eventType, dataLines.join("\n")));
    } catch {
      onError("解析验证事件失败");
    }
  };

  return {
    push(text) {
      buffer += text;
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() || "";
      for (const frame of frames) {
        processFrame(frame);
      }
      return true;
    },
    flush() {
      if (buffer.trim()) {
        processFrame(buffer);
        buffer = "";
      }
      return true;
    },
  };
}
