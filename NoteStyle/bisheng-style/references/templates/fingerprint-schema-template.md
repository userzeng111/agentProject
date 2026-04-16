# Fingerprint Schema 模板

> 用于把小说分析结果压成“作品级操作系统”。

```markdown
# [小说名] Fingerprint Schema

## schema_meta

- work_id:
- work_title:
- author:
- genre_tags:
- source_mode:
- fingerprint_version:
- generated_at:

## evidence_index

| evidence_id | source_type | chapter_range | labels | supports_slots | confidence |
|-------------|-------------|---------------|--------|----------------|------------|
| E-001 | 原文 | 第1-3章 |  |  |  |

## base_runtime_contract

- input_contract:
- phase_pipeline:
- output_contract:
- review_routes:
- guardrail_taxonomy:

## genre_profile

- genre_name:
- core_drivers:
- default_scene_spaces:
- default_line_mix:
- default_hook_types:
- genre_risks:

## work_fingerprint_core

### narrative_engine
- stable_patterns:
- parameters:
- anti_patterns:
- evidence_refs:

### language_engine
- stable_patterns:
- parameters:
- anti_patterns:
- evidence_refs:

### emotion_engine
- stable_patterns:
- parameters:
- anti_patterns:
- evidence_refs:

### character_engine
- stable_patterns:
- parameters:
- anti_patterns:
- evidence_refs:

### planning_engine
- stable_patterns:
- parameters:
- anti_patterns:
- evidence_refs:

### scene_engine
- stable_patterns:
- parameters:
- anti_patterns:
- evidence_refs:

## work_guardrails

| guardrail_id | slot_target | risk_statement | must_keep | must_avoid | repair_direction | severity |
|--------------|-------------|----------------|-----------|------------|------------------|----------|
| GR-001 |  |  |  |  |  |  |

## compiled_resource_cards

- volume_outline_card:
- relation_mount_card:
- chapter_exec_card:
- scene_ledger_card:
- failure_card:
- length_alignment_card:

## validation_suite

- suite_version:
- required_gates:
- originality_kill_switch:

## skill_manifest

- generated_files:
- template_refs:
- layer_refs:
- assembly_order:
```
