# v1 到 v2 迁移指南

## 版本差异概览

| 维度 | v1 | v2 |
|------|----|----|
| rules文件数量 | 6个 | 9个 |
| rules文件列表 | narrative, language, character, emotion, scene, constraints | narrative, language, character, emotion, scene, constraints, **plot**, **dialogue**, **encoding** |
| manifest字段 | 无版本标识 | 增加 `rules_version: "v2"` |
| 信息编码 | 散落在constraints.md中 | 独立为encoding.md，含密度标准+动作编码+母题变奏 |
| 情节编织 | 散落在scene.md中 | 独立为plot.md，含单章结构+钩子+节奏曲线+伏笔管理 |
| 对话声学 | 散落在scene.md和language.md中 | 独立为dialogue.md，含潜台词+标签+角色指纹 |

## 迁移步骤

### 步骤1：从 scene.md 提取内容到 plot.md

- 打开 `rules/scene.md`，识别以下内容块：
  - 章节分段模式、各段功能描述、段间过渡方式 → 迁移到 `plot.md` 的"单章结构模板"
  - 章末钩子类型、频率、示例 → 迁移到 `plot.md` 的"章末钩子设计"
  - 全书推进节奏、主线/日常比例 → 迁移到 `plot.md` 的"大节奏曲线"
  - 多线交织规则（如有） → 迁移到 `plot.md` 的"多线交织规则"
  - 伏笔相关描述 → 迁移到 `plot.md` 的"伏笔管理"
- 迁移后从 `scene.md` 中删除这些内容块，保留场景描写和环境构建相关的规则。

### 步骤2：从 scene.md + language.md 提取内容到 dialogue.md

- 从 `rules/scene.md` 中识别对话相关内容：
  - 对话功能描述、占比 → 迁移到 `dialogue.md` 的"对话功能定位"
  - 潜台词模式、频率 → 迁移到 `dialogue.md` 的"潜台词系统"
  - 对话标签使用习惯 → 迁移到 `dialogue.md` 的"对话标签规范"
- 从 `rules/language.md` 中识别对话相关内容：
  - 角色语言辨识度特征 → 迁移到 `dialogue.md` 的"角色语言指纹"
  - 对话推进效率、角色是否直接说真话 → 迁移到 `dialogue.md` 的"对话推进效率"
- 迁移后从原文件中删除这些内容块。

### 步骤3：从 constraints.md 提取内容到 encoding.md

- 打开 `rules/constraints.md`，识别以下内容块：
  - 信息编码密度标准、高密度公式、自检标准 → 迁移到 `encoding.md` 的"信息编码密度标准"
  - 动作编码公式、角色对比模式 → 迁移到 `encoding.md` 的"动作信息编码"
  - 叙述标签密度 → 迁移到 `encoding.md` 的"叙述标签密度"
  - 母题变奏相关规则 → 迁移到 `encoding.md` 的"母题变奏系统"
- 迁移后从 `constraints.md` 中删除这些内容块，保留章节长度硬规则等非编码类约束。

### 步骤4：更新 manifest.yaml

- 在 `manifest.yaml` 中增加字段：`rules_version: "v2"`。
- 确认 `rules` 列表中包含全部9个文件名。
- 如有蒸馏产物路径记录，更新为v2映射关系。

### 步骤5：验证迁移完整性

- 检查3个新rules文件是否已按模板结构填写。
- 检查原6个rules文件中是否残留应迁移但未迁移的内容。
- 对照 `compilation-map.md` 确认所有蒸馏产物的映射关系在v2中均有覆盖。
- 执行静态检查项清单（见 `quality-loop-protocol.md`）。

## 兼容性保证

- v1实例在v2引擎下仍可正常工作。
- 当v2引擎加载v1实例（缺少plot.md、dialogue.md、encoding.md）时，使用引擎通用原则兜底：
  - 缺少 `plot.md` → 使用通用情节编织原则（三幕结构、常规钩子类型）。
  - 缺少 `dialogue.md` → 使用通用对话原则（功能推进型对话、标准标签规范）。
  - 缺少 `encoding.md` → 使用通用编码原则（中等密度、标准动作编码）。
- 引擎通过检查 `manifest.yaml` 中的 `rules_version` 字段判断实例版本：
  - 无该字段或值为 `"v1"` → 按v1兼容模式加载。
  - 值为 `"v2"` → 按v2完整模式加载。
- 兼容模式下会在加载时输出警告信息，提示用户建议升级到v2。
