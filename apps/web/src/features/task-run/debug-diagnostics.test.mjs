import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAgentDebugDiagnostics,
  buildStateCheck,
} from "./debug-diagnostics.mjs";

function workspace(overrides = {}) {
  return {
    meta: {
      status: "drafting",
      current_stage: "drafting",
      current_unit: "chapter-01",
      progress: 42,
      summary: "正在生成正文。",
      ...(overrides.meta || {}),
    },
    recent_events: overrides.recent_events || [],
    ...overrides,
  };
}

test("运行中且无冲突时诊断为运行正常", () => {
  const diagnostics = buildAgentDebugDiagnostics(workspace());

  assert.equal(diagnostics.health.status, "running_normal");
  assert.equal(diagnostics.health.title, "运行正常");
  assert.equal(diagnostics.stateCheck.conflicts.length, 0);
});

test("等待审核但待审核摘要明确不存在时状态不一致优先于可恢复异常", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      meta: {
        status: "waiting_outline_review",
        current_stage: "waiting_outline_review",
      },
      pending_review_summary: {
        present: false,
        stage: "waiting_outline_review",
        summary: "当前没有待审核内容。",
      },
      recovery_options: [
        {
          action: "recover_to_stable",
          available: true,
        },
      ],
    }),
  );

  assert.equal(diagnostics.health.status, "state_conflict");
  assert.equal(diagnostics.stateCheck.status, "error");
  assert.equal(diagnostics.stateCheck.conflicts[0].code, "pending_review_missing");
});

test("可恢复异常优先于等待用户", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      meta: {
        status: "waiting_manual_action",
        current_stage: "drafting",
      },
      allowed_actions: ["recover_to_stable"],
      recommended_action: "recover_to_stable",
      recovery_options: [
        {
          action: "recover_to_stable",
          available: true,
        },
      ],
    }),
  );

  assert.equal(diagnostics.health.status, "recoverable");
  assert.equal(diagnostics.health.title, "可恢复异常");
  assert.equal(diagnostics.stateCheck.status, "ok");
});

test("completed 终态诊断为已终止", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      meta: {
        status: "completed",
        current_stage: "completed",
        progress: 100,
      },
    }),
  );

  assert.equal(diagnostics.health.status, "terminated");
  assert.equal(diagnostics.health.title, "已终止");
});

test("rag_status 缺失只影响 RAG 模块，不影响整体健康结论", () => {
  const diagnostics = buildAgentDebugDiagnostics(workspace());

  assert.equal(diagnostics.health.status, "running_normal");
  assert.equal(diagnostics.rag.status, "unknown");
  assert.equal(diagnostics.rag.title, "RAG 状态未知");
});

test("状态对账证据不足时不误报异常", () => {
  const stateCheck = buildStateCheck(
    workspace({
      meta: {
        status: "waiting_outline_review",
        current_stage: "waiting_outline_review",
      },
    }),
  );

  assert.equal(stateCheck.status, "unknown");
  assert.equal(stateCheck.conflicts.length, 0);
  assert.equal(stateCheck.unknowns[0].code, "pending_review_unknown");
});

test("状态对账输出 items，且冲突、警告、unknown 条目有稳定 UI 字段", () => {
  const conflict = buildStateCheck(
    workspace({
      novel_progress: {
        completed_chapter_count: 5,
        planned_chapter_count: 4,
      },
    }),
  );
  const warning = buildStateCheck(
    workspace({
      meta: {
        status: "waiting_manual_action",
        current_stage: "drafting",
      },
    }),
  );
  const unknown = buildStateCheck(
    workspace({
      meta: {
        status: "waiting_outline_review",
        current_stage: "waiting_outline_review",
      },
    }),
  );

  assert.equal(Array.isArray(conflict.items), true);
  assert.equal(conflict.items[0].label, "章节进度");
  assert.equal(conflict.items[0].status, "error");
  assert.match(conflict.items[0].summary, /已完成章节数/);
  assert.deepEqual(conflict.items[0].evidence, {
    completed: 5,
    planned: 4,
  });
  assert.equal(conflict.conflicts[0].label, "章节进度");
  assert.equal(conflict.conflicts[0].status, "error");
  assert.match(conflict.conflicts[0].summary, /已完成章节数/);
  assert.deepEqual(conflict.conflicts[0].evidence, {
    completed: 5,
    planned: 4,
  });
  assert.equal(warning.warnings[0].label, "人工处理");
  assert.equal(warning.warnings[0].status, "warning");
  assert.deepEqual(warning.warnings[0].evidence, {
    recoveryActionCount: 0,
  });
  assert.equal(unknown.unknowns[0].label, "待审核摘要");
  assert.equal(unknown.unknowns[0].status, "unknown");
  assert.deepEqual(unknown.unknowns[0].evidence, {
    expected: "pending_review_summary",
  });
});

test("终态任务仍有 running Supervisor 子任务时状态不一致", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      meta: {
        status: "completed",
        current_stage: "completed",
        progress: 100,
      },
      supervisor_plan: {
        planner_version: "v1",
        dependencies: [],
        subtasks: [
          {
            id: "draft-01",
            kind: "draft",
            title: "生成第一章",
            status: "running",
          },
        ],
      },
    }),
  );

  assert.equal(diagnostics.health.status, "state_conflict");
  assert.equal(diagnostics.stateCheck.conflicts[0].code, "terminal_supervisor_running");
});

test("章节进度 completed 大于 planned 时状态不一致", () => {
  const stateCheck = buildStateCheck(
    workspace({
      novel_progress: {
        completed_chapter_count: 5,
        planned_chapter_count: 4,
      },
    }),
  );

  assert.equal(stateCheck.status, "error");
  assert.equal(stateCheck.conflicts[0].code, "chapter_progress_overflow");
});

test("LLM 摘要包含调用、缓存、重试、修复、解析失败、模型与耗时信息", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      llm_report: {
        usage_total: {
          input_tokens: 120,
          output_tokens: 80,
          total_tokens: 200,
          cached_tokens: 20,
          cache_read_input_tokens: 10,
        },
        usage_count: 2,
        exchange_count: 3,
        cache_hit_count: 1,
        latest_usage: {
          model: "K2.6",
        },
        timing_by_stage: {
          drafting: {
            call_count: 2,
            total_duration_ms: 9000,
            max_duration_ms: 6000,
            max_first_token_ms: 1800,
            retry_count: 1,
            repair_count: 1,
          },
        },
        slowest_step: {
          stage: "drafting",
          exchange_label: "chapter-01",
          duration_ms: 6000,
        },
        slowest_first_token: {
          stage: "drafting",
          exchange_label: "chapter-01",
          first_token_ms: 1800,
        },
      },
      recent_events: [
        {
          event_type: "json.parse.failed",
          stage: "drafting",
          message: "JSON 解析失败。",
          created_at: "2026-06-23T10:00:00Z",
        },
      ],
    }),
  );

  assert.deepEqual(diagnostics.llm.tokens, {
    inputTokens: 120,
    outputTokens: 80,
    totalTokens: 200,
    cachedTokens: 20,
    cacheReadInputTokens: 10,
  });
  assert.equal(diagnostics.llm.requestCount, 2);
  assert.equal(diagnostics.llm.exchangeCount, 3);
  assert.equal(diagnostics.llm.cacheHitCount, 1);
  assert.equal(diagnostics.llm.retryCount, 1);
  assert.equal(diagnostics.llm.repairCount, 1);
  assert.equal(diagnostics.llm.jsonParseFailedCount, 1);
  assert.equal(diagnostics.llm.latestModel, "K2.6");
  assert.equal(diagnostics.llm.stageTimings[0].stage, "drafting");
  assert.equal(diagnostics.llm.stageTimings[0].callCount, 2);
  assert.equal(diagnostics.llm.slowestStep.exchangeLabel, "chapter-01");
  assert.equal(diagnostics.llm.slowestFirstToken.firstTokenMs, 1800);
});

test("LLM 最慢步骤可从 recent_events timing_details 兜底派生", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      recent_events: [
        {
          event_type: "context.history.updated",
          stage: "drafting",
          unit_id: "chapter-01",
          message: "记录模型调用耗时。",
          created_at: "2026-06-23T10:00:00Z",
          payload: {
            exchange_label: "chapter-01",
            timing_details: [
              {
                stage: "drafting",
                exchange_label: "chapter-01-fast",
                model: "K2.6",
                duration_ms: 3200,
                first_token_ms: 2500,
                status: "success",
              },
              {
                stage: "drafting",
                exchange_label: "chapter-01-slow",
                model: "K2.6",
                duration_ms: 12800,
                first_token_ms: 900,
                status: "success",
              },
            ],
          },
        },
        {
          event_type: "context.history.updated",
          stage: "verification",
          unit_id: "full-story-verification",
          message: "记录验证调用耗时。",
          created_at: "2026-06-23T10:01:00Z",
          payload: {
            exchange_label: "full-story-verification",
            timing_details: [
              {
                stage: "verification",
                exchange_label: "verification-first-token",
                model: "K2.6",
                duration_ms: 6400,
                first_token_ms: 4800,
                status: "success",
              },
            ],
          },
        },
      ],
    }),
  );

  assert.equal(diagnostics.llm.slowestStep.exchangeLabel, "chapter-01-slow");
  assert.equal(diagnostics.llm.slowestStep.durationMs, 12800);
  assert.equal(diagnostics.llm.slowestFirstToken.exchangeLabel, "verification-first-token");
  assert.equal(diagnostics.llm.slowestFirstToken.firstTokenMs, 4800);
});

test("LLM usage_total 为空对象时从事件用量兜底统计 token", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      llm_report: {
        usage_total: {},
        usage_count: 0,
      },
      recent_events: [
        {
          event_type: "model.usage",
          stage: "drafting",
          message: "模型调用用量已更新。",
          created_at: "2026-06-23T10:00:00Z",
          payload: {
            input_tokens: 100,
            output_tokens: 60,
            total_tokens: 160,
            cached_tokens: 20,
            cache_read_input_tokens: 10,
            model: "K2.6",
          },
        },
      ],
    }),
  );

  assert.deepEqual(diagnostics.llm.tokens, {
    inputTokens: 100,
    outputTokens: 60,
    totalTokens: 160,
    cachedTokens: 20,
    cacheReadInputTokens: 10,
  });
  assert.equal(diagnostics.llm.requestCount, 0);
});

test("Agent Trace 摘要包含最近轮次、计数、评分、问题、警告和结论", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      auto_review_trace: [
        {
          __summary__: true,
          trace_round: 2,
          review_type: "chapter_pair_review",
          overall_score: 86,
          approved: false,
          comment: "需要补充伏笔。",
        },
        {
          agent_id: "main",
          role: "orchestrator",
          execution_kind: "main_agent",
          status: "completed",
        },
        {
          agent_id: "structure",
          role: "structure",
          execution_kind: "subagent",
          status: "completed",
          score: 88,
          issues: [{ severity: "medium" }, { severity: "low" }],
          warnings: [{ severity: "low" }],
        },
        {
          agent_id: "style",
          role: "style",
          execution_kind: "subagent",
          status: "failed",
          score: 0,
          issues: [{ severity: "high" }],
        },
      ],
      agent_runs: [
        {
          id: "run-1",
          subtask_id: "draft-01",
          agent_name: "正文 Agent",
          role: "draft",
          status: "completed",
        },
        {
          id: "run-2",
          subtask_id: "review-01",
          agent_name: "审核 Agent",
          role: "review",
          status: "failed",
        },
      ],
    }),
  );

  assert.equal(diagnostics.agentTrace.round, 2);
  assert.equal(diagnostics.agentTrace.completedCount, 1);
  assert.equal(diagnostics.agentTrace.failedCount, 1);
  assert.equal(diagnostics.agentTrace.displayScore, 86);
  assert.equal(diagnostics.agentTrace.issueCount, 3);
  assert.equal(diagnostics.agentTrace.warningCount, 1);
  assert.equal(diagnostics.agentTrace.verdict, "需处理");
  assert.equal(diagnostics.agentTrace.comment, "需要补充伏笔。");
  assert.equal(diagnostics.agentTrace.runCount, 2);
});

test("终态文案任务已完成事件流已关闭识别为正常终止", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      meta: {
        status: "completed",
        current_stage: "completed",
        progress: 100,
      },
    }),
    {
      eventStreamState: "任务已完成，事件流已关闭",
    },
  );

  assert.equal(diagnostics.connection.status, "terminal_completed");
  assert.equal(diagnostics.connection.tone, "success");
  assert.equal(diagnostics.health.status, "terminated");
});

test("终态连接文案可识别取消、失败和通用结束", () => {
  const cancelled = buildAgentDebugDiagnostics(workspace(), {
    eventStreamState: "任务已取消，事件流已关闭",
  });
  const failed = buildAgentDebugDiagnostics(workspace(), {
    eventStreamState: "任务失败，事件流已关闭",
  });
  const closed = buildAgentDebugDiagnostics(workspace(), {
    eventStreamState: "任务已结束，事件流已关闭",
  });

  assert.equal(cancelled.connection.status, "terminal_cancelled");
  assert.equal(cancelled.connection.tone, "warning");
  assert.equal(failed.connection.status, "terminal_failed");
  assert.equal(failed.connection.tone, "error");
  assert.equal(closed.connection.status, "terminal_closed");
  assert.equal(closed.connection.tone, "default");
});

test("RAG 诊断覆盖未启用、未就绪、已就绪和已注入", () => {
  const disabled = buildAgentDebugDiagnostics(
    workspace({
      rag_status: {
        enabled: false,
        ready: false,
        summary: "RAG 未启用。",
      },
    }),
  );
  const notReady = buildAgentDebugDiagnostics(
    workspace({
      rag_status: {
        enabled: true,
        ready: false,
        last_error: "索引尚未构建",
      },
    }),
  );
  const ready = buildAgentDebugDiagnostics(
    workspace({
      rag_status: {
        enabled: true,
        ready: true,
        injected: false,
        summary: "RAG 已启用且索引可用。",
      },
    }),
  );
  const injected = buildAgentDebugDiagnostics(
    workspace({
      rag_status: {
        enabled: true,
        ready: true,
        injected: true,
        last_query_stage: "drafting",
        injection_evidence: "event",
      },
    }),
  );

  assert.equal(disabled.rag.status, "disabled");
  assert.equal(disabled.rag.title, "RAG 未启用");
  assert.equal(disabled.rag.tone, "default");
  assert.equal(disabled.rag.summary, "RAG 未启用。");
  assert.equal(notReady.rag.status, "not_ready");
  assert.equal(notReady.rag.title, "RAG 未就绪");
  assert.equal(notReady.rag.tone, "warning");
  assert.match(notReady.rag.summary, /尚未就绪/);
  assert.equal(ready.rag.status, "ready");
  assert.equal(ready.rag.title, "RAG 已就绪");
  assert.equal(ready.rag.tone, "success");
  assert.equal(ready.rag.summary, "RAG 已启用且索引可用。");
  assert.equal(injected.rag.status, "injected");
  assert.equal(injected.rag.title, "RAG 已注入");
  assert.equal(injected.rag.tone, "success");
  assert.match(injected.rag.summary, /已注入上下文/);
});

test("上下文摘要汇总 context_status、响应缓存和模型窗口能力", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      context_status: {
        stage: "drafting",
        status: "ok",
        summary: "上下文预算正常。",
        current_tokens: 1200,
        input_tokens: 900,
        output_tokens: 300,
        max_input_tokens: 8000,
        window_usage_ratio: 0.15,
        compression_applied: true,
        compression_ratio: 0.42,
        compression_summary: "已压缩历史摘要。",
        cache_hit: true,
        cache_scope: "runtime_context",
        cached_segments: 3,
      },
      response_cache_status: {
        stage: "drafting",
        status: "hit",
        summary: "响应缓存命中。",
        cache_hit: true,
        exchange_label: "chapter-01",
      },
      request_preview: {
        prompt: "敏感 prompt 不应进入诊断。",
        model_capabilities: {
          context_window: {
            max_input_tokens: 16000,
            max_output_tokens: 4000,
            max_total_tokens: 20000,
            recommended_input_tokens: 12000,
            compression_trigger_tokens: 14000,
          },
        },
      },
    }),
  );

  assert.equal(diagnostics.context.status, "available");
  assert.equal(diagnostics.context.stage, "drafting");
  assert.equal(diagnostics.context.stageStatus, "ok");
  assert.equal(diagnostics.context.summary, "上下文预算正常。");
  assert.deepEqual(diagnostics.context.tokens, {
    currentTokens: 1200,
    inputTokens: 900,
    outputTokens: 300,
    maxInputTokens: 8000,
  });
  assert.equal(diagnostics.context.windowUsageRatio, 0.15);
  assert.deepEqual(diagnostics.context.compression, {
    applied: true,
    ratio: 0.42,
    summary: "已压缩历史摘要。",
  });
  assert.equal(diagnostics.context.cache.contextCacheHit, true);
  assert.equal(diagnostics.context.cache.responseCacheHit, true);
  assert.equal(diagnostics.context.modelContextWindow.maxInputTokens, 16000);
  assert.equal(diagnostics.context.items.some((item) => item.label === "响应缓存" && item.status === "hit"), true);
});

test("上下文摘要空数据降级为中文 unknown 空态", () => {
  const diagnostics = buildAgentDebugDiagnostics(workspace());

  assert.equal(diagnostics.context.status, "unknown");
  assert.equal(diagnostics.context.title, "上下文状态未知");
  assert.match(diagnostics.context.summary, /未提供/);
  assert.deepEqual(diagnostics.context.items, []);
});

test("created 和 sources_ingested 诊断为等待用户", () => {
  for (const status of ["created", "sources_ingested"]) {
    const diagnostics = buildAgentDebugDiagnostics(
      workspace({
        meta: {
          status,
          current_stage: status,
        },
      }),
    );

    assert.equal(diagnostics.health.status, "waiting_user");
    assert.equal(diagnostics.health.title, "等待用户");
  }
});

test("证据链接只输出事件 md/json 引用，不展开事件内容", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      recent_events: [
        {
          event_id: "evt-1",
          event_type: "chapter.saved",
          stage: "drafting",
          unit_id: "chapter-01",
          message: "第一章正文保存完成。",
          md_ref: "tasks/task-1/events/chapter-01.md",
          json_ref: "tasks/task-1/events/chapter-01.json",
          created_at: "2026-06-23T10:00:00Z",
          payload: {
            chapter_summary: "不应被展开。",
          },
        },
      ],
    }),
  );

  assert.deepEqual(diagnostics.evidenceLinks.slice(0, 4), [
    {
      category: "request",
      label: "请求快照",
      summary: "任务输入和模型配置摘要。",
      path: "request.json",
    },
    {
      category: "trace",
      label: "当前 Trace",
      summary: "当前 Agent Trace 轮次摘要。",
      path: "trace/current.json",
    },
    {
      category: "context",
      label: "上下文历史",
      summary: "上下文历史与缓存摘要。",
      path: "context/history.json",
    },
    {
      category: "artifact",
      label: "产物索引",
      summary: "任务产物索引摘要。",
      path: "artifacts/index.json",
    },
  ]);
  assert.equal(diagnostics.evidenceLinks.at(-1).category, "event");
  assert.equal(diagnostics.evidenceLinks.at(-1).eventId, "evt-1");
  assert.equal(diagnostics.evidenceLinks.at(-1).mdRef, "tasks/task-1/events/chapter-01.md");
  assert.equal(diagnostics.evidenceLinks.at(-1).jsonRef, "tasks/task-1/events/chapter-01.json");
  assert.equal(JSON.stringify(diagnostics.evidenceLinks).includes("不应被展开"), false);
});

test("诊断 JSON 不泄露 prompt、raw_response、RAG 命中文本和事件正文", () => {
  const diagnostics = buildAgentDebugDiagnostics(
    workspace({
      request_preview: {
        prompt: "PROMPT_SECRET_请不要泄露",
        model_capabilities: {
          context_window: {
            max_input_tokens: 16000,
          },
        },
      },
      context_status: {
        stage: "drafting",
        status: "ok",
        summary: "上下文预算正常。",
      },
      rag_status: {
        enabled: true,
        ready: true,
        injected: true,
        summary: "RAG 已启用且索引可用。",
        hits: [{ text: "RAG_HIT_SECRET_请不要泄露" }],
        contexts: ["RAG_CONTEXT_SECRET_请不要泄露"],
        selected_contexts: [{ content: "RAG_SELECTED_CONTEXT_SECRET_请不要泄露" }],
        references_text: "RAG_REFERENCE_SECRET_请不要泄露",
      },
      auto_review_trace: [
        {
          __summary__: true,
          trace_round: 1,
          overall_score: 80,
          raw_response: {
            content: "RAW_RESPONSE_SECRET_请不要泄露",
          },
        },
      ],
      recent_events: [
        {
          event_id: "evt-secret",
          event_type: "chapter.saved",
          stage: "drafting",
          message: "章节已保存。",
          md_ref: "tasks/task-1/events/secret.md",
          json_ref: "tasks/task-1/events/secret.json",
          created_at: "2026-06-23T10:00:00Z",
          payload: {
            content: "EVENT_CONTENT_SECRET_请不要泄露",
            chapter_summary: "EVENT_SUMMARY_SECRET_请不要泄露",
          },
        },
      ],
    }),
  );
  const serialized = JSON.stringify(diagnostics);

  assert.equal(serialized.includes("PROMPT_SECRET"), false);
  assert.equal(serialized.includes("RAW_RESPONSE_SECRET"), false);
  assert.equal(serialized.includes("RAG_HIT_SECRET"), false);
  assert.equal(serialized.includes("RAG_CONTEXT_SECRET"), false);
  assert.equal(serialized.includes("RAG_SELECTED_CONTEXT_SECRET"), false);
  assert.equal(serialized.includes("RAG_REFERENCE_SECRET"), false);
  assert.equal(serialized.includes("EVENT_CONTENT_SECRET"), false);
  assert.equal(serialized.includes("EVENT_SUMMARY_SECRET"), false);
});
