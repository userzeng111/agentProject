import assert from "node:assert/strict";
import test from "node:test";

import {
  derivePrimaryRecoveryAction,
  resolveRecoveryPreview,
  filterRecoveryModels,
} from "./recovery-state.mjs";

test("无稳定阶段时主 CTA 退化为查看恢复方案", () => {
  const result = derivePrimaryRecoveryAction({
    recommended_action: "restart_from_input",
    recovery_options: [
      { action: "recover_to_stable", available: false },
      { action: "restart_from_input", available: true },
    ],
  });

  assert.equal(result.label, "查看恢复方案");
  assert.equal(result.action, "restart_from_input");
});

test("存在稳定阶段时主 CTA 固定优先回填最近稳定阶段", () => {
  const result = derivePrimaryRecoveryAction({
    recommended_action: "restart_from_input",
    recovery_options: [
      { action: "recover_to_stable", available: true, label: "回填最近稳定阶段" },
      { action: "restart_from_input", available: true, label: "按原始输入重新开始" },
    ],
  });

  assert.equal(result.label, "回填最近稳定阶段");
  assert.equal(result.action, "recover_to_stable");
});

test("通过 recovery_options 解析当前 action preview", () => {
  const preview = resolveRecoveryPreview(
    {
      recommended_action: "recover_to_stable",
      recovery_options: [
        {
          action: "recover_to_stable",
          available: true,
          preview: {
            target_stage: "waiting_chapter_review",
            target_stage_label: "待章节审核",
            allowed_model_ids: ["gpt-5.4", "glm-5.1"],
          },
        },
        {
          action: "restart_from_input",
          available: true,
          preview: {
            target_stage: "planning",
            target_stage_label: "重新开始规划",
            allowed_model_ids: ["gpt-5.4"],
          },
        },
      ],
    },
    "recover_to_stable",
  );

  assert.deepEqual(preview, {
    target_stage: "waiting_chapter_review",
    target_stage_label: "待章节审核",
    allowed_model_ids: ["gpt-5.4", "glm-5.1"],
  });
});

test("模型列表按 allowed_model_ids 过滤", () => {
  const models = [
    { id: "gpt-5.4", display_name: "GPT 5.4" },
    { id: "glm-5.1", display_name: "GLM 5.1" },
    { id: "deepseek-v3", display_name: "DeepSeek V3" },
  ];

  const filtered = filterRecoveryModels(models, ["glm-5.1", "gpt-5.4"]);

  assert.deepEqual(filtered, [
    { id: "gpt-5.4", display_name: "GPT 5.4" },
    { id: "glm-5.1", display_name: "GLM 5.1" },
  ]);
});

test("allowed_model_ids 缺失时模型过滤 fail-close", () => {
  const models = [
    { id: "gpt-5.4", display_name: "GPT 5.4" },
    { id: "glm-5.1", display_name: "GLM 5.1" },
  ];

  const filtered = filterRecoveryModels(models, undefined);

  assert.deepEqual(filtered, []);
});
