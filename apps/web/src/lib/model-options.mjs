export function isGatewayBackedModel(model) {
  const source = String(model?.metadata?.source || "").trim();
  return source.includes("gateway");
}

export function isNovelTaskModelSupported(model) {
  return isGatewayBackedModel(model) && String(model?.metadata?.compatibility || "").trim() === "verified";
}

export function selectNovelTaskModels(models) {
  return (models || []).filter((item) => isNovelTaskModelSupported(item));
}
