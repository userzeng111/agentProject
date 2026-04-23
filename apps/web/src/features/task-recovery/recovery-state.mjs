const RECOVER_TO_STABLE = "recover_to_stable";
const VIEW_PLAN_LABEL = "查看恢复方案";
const DEFAULT_STABLE_LABEL = "回填最近稳定阶段";

function getRecoveryOptions(recovery) {
  return Array.isArray(recovery?.recovery_options) ? recovery.recovery_options : [];
}

function findRecoveryOption(recovery, action) {
  return getRecoveryOptions(recovery).find((option) => option?.action === action) ?? null;
}

function resolvePreferredRecoveryOption(recovery) {
  const recommendedAction = typeof recovery?.recommended_action === "string" ? recovery.recommended_action : "";
  const recommendedOption = recommendedAction ? findRecoveryOption(recovery, recommendedAction) : null;
  if (recommendedOption?.available) {
    return recommendedOption;
  }

  return getRecoveryOptions(recovery).find((option) => option?.available) ?? null;
}

export function derivePrimaryRecoveryAction(recovery) {
  const stableOption = findRecoveryOption(recovery, RECOVER_TO_STABLE);
  if (stableOption?.available) {
    return {
      action: stableOption.action,
      label: typeof stableOption.label === "string" && stableOption.label.trim() ? stableOption.label.trim() : DEFAULT_STABLE_LABEL,
      option: stableOption,
    };
  }

  const preferredOption = resolvePreferredRecoveryOption(recovery);
  if (!preferredOption) {
    return null;
  }

  return {
    action: preferredOption.action,
    label: VIEW_PLAN_LABEL,
    option: preferredOption,
  };
}

export function resolveRecoveryPreview(recovery, action) {
  const option = action ? findRecoveryOption(recovery, action) : resolvePreferredRecoveryOption(recovery);
  return option?.preview ?? null;
}

export function filterRecoveryModels(models, allowedModelIds) {
  const candidates = Array.isArray(models)
    ? models.filter((model) => typeof model?.id === "string" && model.id.trim())
    : [];

  if (!Array.isArray(allowedModelIds)) {
    return [];
  }

  const allowedIds = new Set(
    allowedModelIds
      .filter((modelId) => typeof modelId === "string" && modelId.trim())
      .map((modelId) => modelId.trim()),
  );

  return candidates.filter((model) => allowedIds.has(model.id.trim()));
}
