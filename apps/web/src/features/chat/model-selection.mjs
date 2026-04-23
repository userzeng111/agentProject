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
