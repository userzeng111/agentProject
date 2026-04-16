# Skill Manifest 模板

> 用于把 `Fingerprint Schema` 编译成实例 skill 的文件映射。

```yaml
skill_manifest:
  work_id: ""
  output_root: ""
  generated_files:
    - path: "SKILL.md"
      source: "skill-template.md"
    - path: "fingerprint/schema-meta.md"
      source: "fingerprint-schema-template.md"
    - path: "validation/suite.yaml"
      source: "validation-suite-template.yaml"
    - path: "validation/repair-map.md"
      source: "repair-map-template.md"
    - path: "validation/reports/final_report.md"
      source: "validation-final-report-template.md"
    - path: "validation/reports/repair_report.md"
      source: "repair-report-template.md"

  template_refs:
    skill_template: ""
    fingerprint_template: ""
    validation_suite_template: ""
    validation_report_template: ""
    repair_map_template: ""
    repair_report_template: ""

  layer_refs:
    base_runtime_contract: ""
    genre_profile: ""
    work_fingerprint_core: ""
    work_guardrails: ""
    validation_suite: ""

  assembly_order:
    - "compile fingerprint"
    - "compile guardrails"
    - "compile resource cards"
    - "compile validation suite"
    - "assemble SKILL.md"
```
