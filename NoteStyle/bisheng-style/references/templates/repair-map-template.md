# Auto Repair Map 模板

> 把失败类型映射成固定回修动作。

```markdown
# Auto Repair Map

## repair_policy

- enabled: true
- max_passes: 2
- fail_fast:
  - originality_kill_switch

## static_routes

| trigger | repair_action | target_files | rerun_gates |
|---------|---------------|--------------|-------------|
| G0 schema_completeness failed | 补缺失槽位并重编 fingerprint | fingerprint/* | G0 |
| G1 evidence_traceability failed | 补 evidence_index 与 engine evidence_refs | fingerprint/evidence-index.md, fingerprint/work-fingerprint-core.md | G1 |
| G2 guardrail_executability failed | 把空话 guardrail 改写为“风险-保留-避免-修复” | fingerprint/work-guardrails.md | G2 |
| G3 resource_card_usability failed | 重编资源卡，补执行字段 | resource/* | G3 |

## generation_routes

| trigger | repair_action | target_files | rerun_gates |
|---------|---------------|--------------|-------------|
| G4 scene_reproduction failed | 重写场景，补高层社会接口、围观误判、主角收手 | validation/outputs/scene/* | G4 |
| G5 chapter_reproduction failed | 重写单章，补双位移、字数、章尾变量 | validation/outputs/chapter/* | G5 |
| G6 arc_stability_3chap failed | 扩写弱章、补社会压力、补章间牵引 | validation/outputs/arc/* | G6 |
| G7 negative_case_blocking failed | 补坏稿样例并重跑拦截 | validation/negative_cases/* | G7 |

## dimension_routes

| trigger | repair_action | target_files | rerun_gates |
|---------|---------------|--------------|-------------|
| relationship_diff low | 生成第二条关系线对照三章样例 | validation/briefs/arc_3chap_002.md, validation/outputs/arc_002/* | G6 |
| social_pressure low | 给场面补老师/家长/老板/保安等更高层接口 | validation/outputs/scene/*, validation/outputs/arc/* | G4,G6 |
| language_signature low | 收紧句长、增强补刀旁白、去掉工整句 | validation/outputs/* | G4,G5,G6 |
| emotion_carrier low | 改成动作优先，删直白表白和长内心戏 | validation/outputs/* | G4,G5,G6 |
```
