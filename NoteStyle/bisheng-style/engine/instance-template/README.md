# 实例模板使用说明

本目录是笔生skill的实例模板，用于新小说蒸馏时创建风格实例。

## 使用流程

1. 复制本目录到 `instances/[instance-id]/`
2. 填写 `manifest.yaml` 中的元数据
3. 运行蒸馏流程（Phase 0-5）
4. 将蒸馏结果填入对应规则文件
5. 在 `instances/registry.yaml` 中注册新实例

## 实例ID命名规则

- 使用小说名的英文拼音或缩写
- 全小写，用短横线分隔
- 示例：`wozhenmeixiangchongshengya`、`tiancantang`、`guoman`

## 文件填写指南

每个规则文件中的 `<!-- -->` 注释区域是指引，填写时删除注释替换为实际内容。

规则来源是蒸馏产物 `references/research/[novel-name]/` 下的分析文件。

## 加载优先级

| 优先级 | 标记 | 文件 | 说明 |
|--------|------|------|------|
| P0 | 始终加载 | manifest.yaml, rules/*.md | 核心风格规则 |
| P1 | 创作前加载 | examples/*.md | 场景参考 |
| P2 | 按需加载 | validation/ | 验证与对比 |

## 质量标准

实例完成后必须通过引擎的 Phase 4 验证门才能标记为 `status: active`。
