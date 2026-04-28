export function isGatewayBackedModel(model) {
  const source = String(model?.metadata?.source || "").trim();
  return source.includes("gateway");
}

export function isNovelTaskModelSupported(model) {
  return isGatewayBackedModel(model);
}

export function selectNovelTaskModels(models) {
  return (models || []).filter((item) => isNovelTaskModelSupported(item));
}
