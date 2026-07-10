export function isGatewayBackedModel(model) {
  const source = String(model?.metadata?.source || "").trim();
  return source.includes("gateway");
}

export function getModelValidationLabel(model) {
  const validationStatus = model?.metadata?.validation?.status;
  const compatibility = model?.metadata?.compatibility;
  if (validationStatus === "failed") {
    return "最近验证失败";
  }
  if (validationStatus === "running") {
    return "验证中";
  }
  if (validationStatus === "verified" || compatibility === "verified") {
    return "已验证";
  }
  return "未验证";
}

export function resolveConversationModel(savedModel, models) {
  const savedGatewayModel =
    savedModel &&
    (models || []).some((item) => item.id === savedModel && isGatewayBackedModel(item))
      ? savedModel
      : "";
  return savedGatewayModel;
}

export function resolveChatSelectValue(currentModel, models) {
  const availableModels = (models || []).filter((item) => isGatewayBackedModel(item));
  const current = currentModel || "";
  if (current && availableModels.some((item) => item.id === current)) {
    return current;
  }
  return "";
}
