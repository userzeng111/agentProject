export const CREATE_WORKBENCH_STAGES = Object.freeze([
  { key: "story", label: "故事核心" },
  { key: "reference", label: "参考与边界" },
  { key: "execution", label: "篇幅与执行" },
]);

function hasText(value) {
  return typeof value === "string" && Boolean(value.trim());
}

function hasPositiveNumber(value) {
  return Number.isFinite(Number(value)) && Number(value) > 0;
}

function needsStyleProfile(payload) {
  return ["fanfic", "style_remix"].includes(payload?.creative_mode);
}

function needsFixedReviewModel(payload) {
  return Boolean(payload?.auto_review) && payload?.auto_review_model_mode === "fixed";
}

function resolveValidity(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}

/**
 * 生成创建任务页的准备度清单，并返回第一个未完成项。
 * 外部校验状态缺省时，模型和风格实例仅按 payload 是否已选择判断。
 */
export function resolveCreateWorkbenchReadiness({
  payload = {},
  ragAvailable = false,
  hasValidCreativeModel,
  hasValidReviewModel,
  hasStyleProfile,
} = {}) {
  const styleProfileRequired = needsStyleProfile(payload);
  const fixedReviewModelRequired = needsFixedReviewModel(payload);
  const creativeModelReady = resolveValidity(hasValidCreativeModel, hasText(payload.model_id));
  const reviewModelReady = resolveValidity(hasValidReviewModel, hasText(payload.review_model_id));
  const styleProfileReady = resolveValidity(hasStyleProfile, hasText(payload.style_profile_id));
  const items = [
    {
      key: "prompt",
      label: "创意提示词",
      stage: "story",
      complete: hasText(payload.prompt),
      incompleteHint: "请填写创意提示词",
    },
    {
      key: "creative-model",
      label: "创作模型",
      stage: "story",
      complete: creativeModelReady,
      incompleteHint: "请选择可用的创作模型",
    },
    {
      key: "chapters",
      label: "目标章节数",
      stage: "story",
      complete: hasPositiveNumber(payload.target_chapter_count),
      incompleteHint: "请填写目标章节数",
    },
    {
      key: "rag",
      label: "小说知识库",
      stage: "execution",
      complete: ragAvailable === true,
      incompleteHint: "请先完成知识库同步",
    },
  ];

  if (styleProfileRequired) {
    items.push({
      key: "style-profile",
      label: "参考实例",
      stage: "reference",
      complete: styleProfileReady,
      incompleteHint: "请选择参考实例",
    });
  }

  if (fixedReviewModelRequired) {
    items.push({
      key: "review-model",
      label: "固定审核模型",
      stage: "execution",
      complete: reviewModelReady,
      incompleteHint: "请选择可用的固定审核模型",
    });
  }

  return {
    items,
    firstIncomplete: items.find((item) => !item.complete) ?? null,
  };
}

/**
 * 按创建工作台三阶段汇总完成状态，阶段状态与准备度清单使用同一套判定。
 */
export function resolveCreateWorkbenchStages(options = {}) {
  const { items } = resolveCreateWorkbenchReadiness(options);
  return CREATE_WORKBENCH_STAGES.map((stage) => {
    const stageItems = items.filter((item) => item.stage === stage.key);
    return {
      ...stage,
      complete: stageItems.every((item) => item.complete),
    };
  });
}
