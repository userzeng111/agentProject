import { Page, Route } from "@playwright/test";

type WorkspaceOverrides = Record<string, unknown>;

const now = new Date("2026-06-24T00:00:00.000Z").toISOString();

export function makeTask(status = "created", taskId = "task_playwright_fixture") {
  return {
    id: taskId,
    task_id: taskId,
    status,
    title: `自动化测试-${status}`,
    summary: "Playwright fixture 摘要",
    current_stage: status,
    updated_at: now,
    created_at: now,
    storage_state: "active",
    mode: "original",
    creative_mode: "original",
    novel_size: "short",
    input: {
      creative_mode: "original",
      novel_size: "short",
      prompt: "fixture prompt",
      genre: "测试",
      style: "清晰",
      chapter_word_min: 1000,
      title_hint: "fixture",
    },
  };
}

export function makeDashboard() {
  return {
    continue_tasks: [makeTask("created", "task_created_fixture")],
    running_tasks: [makeTask("planning", "task_running_fixture")],
    failed_tasks: [makeTask("failed", "task_failed_fixture")],
    completed_tasks: [makeTask("completed", "task_completed_fixture")],
    model_summary: {},
    system_summary: {},
    continue_total: 1,
    running_total: 1,
    failed_total: 1,
    completed_total: 1,
  };
}

export function makeWorkspace(status = "created", overrides: WorkspaceOverrides = {}) {
  const taskId = String(overrides.task_id ?? "task_playwright_fixture");
  const meta = {
    task_id: taskId,
    title: `自动化测试-${status}`,
    summary: "Playwright fixture 摘要",
    status,
    current_stage: status,
    created_at: now,
    updated_at: now,
    mode: "original",
    creative_mode: "original",
    novel_size: "short",
    auto_review: false,
    model_id: "gpt-5.4",
    default_model_id: "gpt-5.4",
    creative_model_id: "gpt-5.4",
    review_model_id: "gpt-5.4",
    error_message: status === "waiting_manual_action" ? "测试恢复分支" : "",
    last_error_detail: "",
  };
  const base = {
    meta,
    recent_events: [
      {
        event_id: "event_fixture_1",
        event_type: status === "completed" ? "task.completed" : "task.created",
        stage: status,
        message: "测试事件摘要",
        created_at: now,
        md_ref: "/tasklog/runs/task_playwright_fixture/events.md",
      },
    ],
    active_trace_summary: status === "planning" ? "正在规划测试摘要" : "",
    available_tabs: ["request", "events", "supervisor", "debug"],
    allowed_actions: status === "waiting_manual_action" ? ["recover"] : [],
    recommended_action: status === "waiting_manual_action" ? "recover_to_stable" : "",
    blocked_reason: "",
    state_reconciled: false,
    reconciliation_kind: "",
    reconciliation_summary: "",
    recovery_options:
      status === "waiting_manual_action"
        ? [
            {
              action: "recover_to_stable",
              label: "恢复到最近稳定阶段",
              available: true,
              reason: "",
              preview: {
                target_stage: "created",
                target_stage_label: "任务准备",
                will_resume_generation: false,
                allowed_model_ids: ["gpt-5.4"],
                default_model_id: "gpt-5.4",
              },
            },
          ]
        : [],
    request_preview: {
      prompt: "测试请求摘要",
      genre: "测试",
      style: "清晰",
    },
    context_status: {
      stage: status,
      status: "ok",
      summary: "上下文预算正常。",
      input_tokens: 120,
      max_input_tokens: 8000,
    },
    response_cache_status: {
      status: "miss",
      summary: "响应缓存未命中。",
      history_count: 0,
    },
    pending_review_summary: {
      present: false,
      review_type: "",
      stage: status,
      batch_index: null,
      revision_count: 0,
      outline_phase: "",
      summary: "当前没有待审核内容。",
    },
    rag_status: {
      enabled: true,
      ready: true,
      source: "fixture",
      summary: "RAG 已启用且索引可用。",
      last_query_stage: "",
      last_error: "",
      injected: false,
      injection_evidence: "",
    },
    llm_report: {
      request_count: status === "planning" ? 1 : 0,
      usage_total: {},
      stage_timings: [],
      slowest_step: "",
      slowest_first_token_ms: null,
      recent_model: "gpt-5.4",
      cache_hits: 0,
      retries: 0,
      repairs: 0,
      json_parse_failures: 0,
    },
    novel_progress: {
      target_chapter_count: 8,
      planned_chapter_count: 8,
      completed_chapter_count: status === "completed" ? 8 : 0,
      next_chapter_number: 1,
      remaining_chapter_count: status === "completed" ? 0 : 8,
      default_batch_size: 3,
    },
    sources: [],
    supervisor_plan: {
      task_id: taskId,
      status,
      subtasks: [
        {
          id: "subtask_fixture",
          name: "测试子任务",
          status: status === "planning" ? "running" : "pending",
          description: "测试 Supervisor 子任务",
        },
      ],
    },
    agent_runs: [],
    auto_review_trace: [],
    outline_phase: "",
    outline_completed_count: 0,
    outline_total_count: 0,
  };
  return {
    ...base,
    ...overrides,
    meta: { ...meta, ...(overrides.meta as Record<string, unknown> | undefined) },
  };
}

export function makeArchiveList() {
  return {
    items: [
      {
        task_id: "task_archive_fixture",
        id: "task_archive_fixture",
        title: "归档测试任务",
        summary: "归档摘要",
        status: "completed",
        current_stage: "completed",
        progress: 100,
        storage_state: "archived",
        mode: "original",
        creative_mode: "original",
        novel_size: "short",
        created_at: now,
        updated_at: now,
        completed_at: now,
        chapter_count: 2,
        word_count: 1200,
      },
    ],
    total: 1,
    page: 1,
    page_size: 10,
  };
}

export function makeArchiveDetail() {
  return {
    meta: {
      task_id: "task_archive_fixture",
      id: "task_archive_fixture",
      title: "归档测试任务",
      status: "completed",
      current_stage: "completed",
      progress: 100,
      storage_state: "archived",
      mode: "original",
      creative_mode: "original",
      novel_size: "short",
      default_model_id: "gpt-5.4",
      updated_at: now,
    },
    request_preview: {
      prompt: "归档测试提示词",
      genre: "测试",
      style: "清晰",
      chapter_word_min: 1000,
    },
    recent_events: [],
    result_summary: "结果摘要",
    result_markdown: "# 归档测试任务\n\n章节内容占位",
    result_md_ref: null,
    chapter_index: [
      { number: 1, title: "第一章", summary: "章节摘要", content: "章节内容占位" },
      { number: 2, title: "第二章", summary: "章节摘要", content: "章节内容占位" },
    ],
    artifact_index: [],
    history_index: [],
    story_plan: {
      working_title: "归档测试任务",
      logline: "归档大纲摘要",
      world_notes: ["测试世界观"],
      character_notes: ["测试角色"],
      planned_chapter_count: 2,
      chapter_plan: [
        { number: 1, title: "第一章", goal: "建立冲突" },
        { number: 2, title: "第二章", goal: "解决冲突" },
      ],
    },
  };
}

export async function mockCommonApiRoutes(page: Page) {
  await page.route("**/api/models**", async (route) => {
    await route.fulfill({
      json: {
        data: [
          {
            id: "gpt-5.4",
            display_name: "GPT 5.4",
            provider: "gateway",
            metadata: { source: "gateway:list_models" },
            capabilities: {
              features: ["novel"],
              context_window: { max_input_tokens: 8000, max_output_tokens: 4000 },
              cache: { runtime_context_cache: true, prompt_cache: true, response_cache: true },
              compression: { supported: true, strategy: "summary" },
            },
          },
        ],
        meta: { default_model: "gpt-5.4", cached: true },
      },
    });
  });
  await page.route("**/api/settings/rag**", async (route) => {
    await route.fulfill({
      json: {
        available: true,
        library_dir: "/tmp/rag",
        faiss_index_path: "/tmp/rag/index.faiss",
        sqlite_path: "/tmp/rag/meta.sqlite",
        sources: ["fixture"],
        last_result: null,
      },
    });
  });
  await page.route("**/api/style-profiles**", async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: "style_fixture",
            name: "测试风格",
            source_novel: "测试小说",
            source_author: "测试作者",
            genre: "测试",
            fidelity_score: 0.9,
          },
        ],
      },
    });
  });
  await page.route("**/api/settings/protocols**", async (route) => {
    await route.fulfill({ json: { default_protocol: "openai", overrides: {} } });
  });
  await page.route("**/api/dashboard**", async (route) => {
    await route.fulfill({ json: makeDashboard() });
  });
  await page.route("**/api/archive**", async (route) => {
    if (route.request().url().includes("/api/archive/task_archive_fixture")) {
      await route.fulfill({ json: makeArchiveDetail() });
      return;
    }
    await route.fulfill({ json: makeArchiveList() });
  });
}

export async function mockTaskWorkspace(page: Page, workspace = makeWorkspace()) {
  const taskId = workspace.meta.task_id;
  const fulfillEventStream = async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `event: snapshot\ndata: ${JSON.stringify({ task_id: taskId })}\n\n`,
    });
  };
  await page.route(`**/api/tasks/${taskId}`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: makeTask(workspace.meta.status, taskId) });
      return;
    }
    await route.fulfill({ json: makeTask(workspace.meta.status, taskId) });
  });
  await page.route(`**/api/tasks/${taskId}/workspace**`, async (route) => {
    await route.fulfill({ json: workspace });
  });
  await page.route(`**/api/tasks/${taskId}/supervisor**`, async (route) => {
    await route.fulfill({ json: workspace.supervisor_plan });
  });
  await page.route(`**/api/tasks/${taskId}/chapters**`, async (route) => {
    await route.fulfill({ json: { task_id: taskId, chapters: [] } });
  });
  await page.route(`**/api/tasks/${taskId}/artifacts**`, async (route) => {
    await route.fulfill({ json: { task_id: taskId, artifacts: [] } });
  });
  await page.route(`**/api/tasks/${taskId}/events/stream**`, fulfillEventStream);
  await page.route(`**/api/tasks/${taskId}/workspace/stream**`, fulfillEventStream);
  await page.route(`**/api/tasks/${taskId}/workspace/events**`, fulfillEventStream);
  await page.route(`**/api/tasks/${taskId}/sse**`, fulfillEventStream);
}
