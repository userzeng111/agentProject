export function isGatewayBackedModel(model) {
  const source = String(model?.metadata?.source || "").trim();
  return source.includes("gateway");
}

export function resolveDefaultChatModelId(models, requestedDefault = "") {
  const gatewayBackedModels = (models || []).filter((item) => isGatewayBackedModel(item));
  const requestedDefaultAvailable = gatewayBackedModels.some((item) => item.id === requestedDefault);
  if (requestedDefaultAvailable) {
    return requestedDefault;
  }
  return gatewayBackedModels[0]?.id ?? "";
}

export function resolveConversationModel(savedModel, models, defaultModelId = "") {
  const savedGatewayModel =
    savedModel &&
    (models || []).some((item) => item.id === savedModel && isGatewayBackedModel(item))
      ? savedModel
      : "";
  return savedGatewayModel || defaultModelId || "";
}

export function resolveChatSelectValue(currentModel, models, defaultModelId = "") {
  const availableModels = (models || []).filter((item) => isGatewayBackedModel(item));
  const current = currentModel || defaultModelId || "";
  if (current && availableModels.some((item) => item.id === current)) {
    return current;
  }
  if (defaultModelId && availableModels.some((item) => item.id === defaultModelId)) {
    return defaultModelId;
  }
  return availableModels[0]?.id ?? "";
}
