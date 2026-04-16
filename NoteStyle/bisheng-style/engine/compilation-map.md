# 蒸馏产物到实例产物的编译映射表

## 映射关系

| 蒸馏产物（输入） | 实例产物（输出） | 映射说明 |
|----------------|----------------|---------|
| 01-narrative-technique.md | rules/narrative.md | 叙事视角、叙述者人格、开头标记、全知反讽、叙事距离控制 |
| 02-language-style.md | rules/language.md | 内心独白口吻、方言俚语、自造词、幽默配方 |
| 03-character-template.md | rules/character.md | 出场配方、安静型角色口语、配角动作指纹 |
| 04-plot-structure.md | rules/plot.md + rules/constraints.md(部分) | 单章结构→plot.md；章节长度→constraints.md |
| 05-emotion-pattern.md | rules/emotion.md | 情感表达方式、爆发节奏、虐心/感动配方 |
| 06-worldbuilding.md | rules/scene.md(文化嵌入部分) | 时代标志物、社会环境、设定体系 |
| 07-info-encoding.md | rules/encoding.md(信息编码部分) | 密度标准、高密度公式、自检标准 |
| 08-dialogue-acoustics.md | rules/dialogue.md | 潜台词系统、信息差类型、角色语言指纹 |
| 09-action-encoding.md | rules/encoding.md(动作编码部分) | 动作拆解、角色对比模式、编码公式 |
| 10-rhetoric-signature.md | rules/language.md(修辞部分) + rules/scene.md(部分) | 比喻系统、通感模式、反讽分类 |
| 11-motif-variation.md | rules/encoding.md(母题部分) | 母题演变轨迹、三步法公式、种子管理 |
| 12-length-baseline.md | rules/constraints.md(章节长度部分) | 章节长度硬规则 |

## 编译流程

1. 读取12个蒸馏分析文件
2. 按映射关系提取各维度的核心规则
3. 将通用性规则写入 rules/ 文件
4. 将具体数值参数写入 constraints.md
5. 验证每个 rules 文件至少有3条来自蒸馏产物的证据支持
