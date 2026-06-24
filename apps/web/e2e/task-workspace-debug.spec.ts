import { expect, test } from "@playwright/test";
import { createDraftTask, deleteTaskIfAllowed, readWorkspace } from "./helpers/api";
import { expectNoSensitiveText, expectVisibleTexts } from "./helpers/assertions";
import { makeWorkspace, mockCommonApiRoutes, mockTaskWorkspace } from "./helpers/fixtures";

test.describe("任务工作台调试中心", () => {
  test("真实 created 任务展示调试 Tab 与七个调试模块", async ({ page, request }) => {
    let taskId = "";
    try {
      const task = await createDraftTask(request, "Playwright 调试中心");
      taskId = task.id;

      const workspace = await readWorkspace(request, taskId);
      expect(workspace).toHaveProperty("pending_review_summary");
      expect(workspace).toHaveProperty("rag_status");

      let workspaceRequests = 0;
      page.on("request", (req) => {
        if (req.url().includes(`/api/tasks/${taskId}/workspace`)) {
          workspaceRequests += 1;
        }
      });

      await page.goto(`/tasks/?id=${taskId}`, { waitUntil: "commit" });
      await page.getByRole("tab", { name: /调试/ }).click();

      for (const text of [
        "诊断结论",
        "实时连接",
        "LLM 摘要",
        "Agent Trace",
        "上下文/RAG",
        "状态对账",
        "最近事件",
        "证据链接",
      ]) {
        await expect(page.getByRole("heading", { name: text, exact: true }), `调试模块：${text}`).toBeVisible();
      }

      await expectNoSensitiveText(page);
      const beforeRefresh = workspaceRequests;
      await page.getByRole("button", { name: "刷新工作区" }).click();
      await expect.poll(() => workspaceRequests, { message: "刷新应重新请求 workspace" }).toBeGreaterThan(beforeRefresh);
    } finally {
      await deleteTaskIfAllowed(request, taskId);
    }
  });

  test("fixture 调试中心展示字段级诊断、RAG 注入、状态对账和恢复入口", async ({ page }) => {
    await mockCommonApiRoutes(page);
    const taskId = "task_debug_rich_fixture";
    let recoverRequests = 0;
    const workspace = makeWorkspace("waiting_outline_review", {
      task_id: taskId,
      meta: {
        task_id: taskId,
        status: "waiting_outline_review",
        current_stage: "waiting_outline_review",
        title: "调试字段覆盖任务",
        default_model_id: "gpt-5.4",
        model_id: "gpt-5.4",
        creative_model_id: "gpt-5.4",
        review_model_id: "gpt-5.4",
      },
      allowed_actions: ["recover"],
      recommended_action: "recover_to_stable",
      recovery_options: [
        {
          action: "recover_to_stable",
          label: "回填最近稳定阶段",
          available: true,
          reason: "",
          preview: {
            target_stage: "planning",
            target_stage_label: "大纲规划",
            target_chapter_numbers: [1, 2],
            will_resume_generation: false,
            default_model_id: "gpt-5.4",
            last_action_model_id: "gpt-5.4",
            allowed_model_ids: ["gpt-5.4"],
          },
        },
      ],
      request_preview: {
        prompt: "调试字段覆盖提示词",
        model_id: "gpt-5.4",
        default_model_id: "gpt-5.4",
        model_capabilities: {
          context_window: {
            max_input_tokens: 8000,
            max_output_tokens: 4000,
            max_total_tokens: 12000,
          },
        },
      },
      context_status: {
        stage: "planning",
        status: "ok",
        summary: "上下文预算正常。",
        current_tokens: 1200,
        input_tokens: 1000,
        output_tokens: 200,
        max_input_tokens: 8000,
        window_usage_ratio: 0.15,
        compression_applied: true,
        compression_ratio: 0.4,
        cache_hit: true,
        cached_segments: 3,
        cache_scope: "task",
      },
      response_cache_status: {
        stage: "planning",
        status: "hit",
        summary: "响应缓存命中。",
        cache_hit: true,
        cache_scope: "task",
        exchange_label: "outline",
        history_count: 2,
      },
      pending_review_summary: {
        present: true,
        review_type: "outline_review",
        stage: "waiting_outline_review",
        batch_index: null,
        revision_count: 1,
        outline_phase: "master",
        summary: "已有待审核大纲摘要。",
      },
      rag_status: {
        enabled: true,
        ready: true,
        source: "context_snapshot",
        summary: "RAG 已注入自动化上下文。",
        last_query_stage: "planning",
        last_error: "",
        injected: true,
        injection_evidence: "context_snapshot:3",
      },
      llm_report: {
        usage_count: 2,
        exchange_count: 3,
        cache_hit_count: 1,
        usage_total: {
          input_tokens: 1000,
          output_tokens: 280,
          total_tokens: 1280,
          cached_tokens: 120,
        },
        timing_by_stage: {
          planning: {
            call_count: 2,
            total_duration_ms: 1200,
            max_duration_ms: 900,
            max_first_token_ms: 300,
            retry_count: 1,
            repair_count: 1,
          },
        },
        latest_usage: { model: "gpt-5.4" },
        slowest_step: {
          stage: "planning",
          exchange_label: "大纲规划",
          model: "gpt-5.4",
          duration_ms: 900,
        },
        slowest_first_token: {
          stage: "planning",
          exchange_label: "首 Token 大纲",
          first_token_ms: 300,
        },
      },
      novel_progress: {
        target_chapter_count: 8,
        planned_chapter_count: 8,
        completed_chapter_count: 1,
      },
      supervisor_plan: {
        planner_version: "fixture",
        dependencies: [],
        subtasks: [
          {
            id: "outline_review",
            kind: "review",
            title: "大纲审核",
            status: "pending",
          },
        ],
      },
      agent_runs: [
        { agent_id: "reviewer_a", status: "completed" },
        { agent_id: "reviewer_b", status: "failed" },
      ],
      auto_review_trace: [
        {
          __summary__: true,
          trace_round: 1,
          review_type: "outline_review",
          overall_score: 82,
          approved: false,
          comment: "自动审核建议人工确认",
        },
        {
          agent_id: "reviewer_a",
          execution_kind: "subagent",
          status: "completed",
          score: 86,
          issues: ["节奏偏快"],
          warnings: ["补充人物动机"],
        },
        {
          agent_id: "reviewer_b",
          execution_kind: "subagent",
          status: "failed",
          issues: [],
          warnings: [],
        },
      ],
      recent_events: [
        {
          event_id: "event_model_usage",
          event_type: "model.usage",
          stage: "planning",
          message: "模型调用完成",
          created_at: new Date("2026-06-24T00:01:00.000Z").toISOString(),
          md_ref: "/tasklog/runs/task_debug_rich_fixture/events.md",
          json_ref: "/tasklog/runs/task_debug_rich_fixture/events.tail.json",
          payload: {
            model: "gpt-5.4",
            timing_details: [
              {
                stage: "planning",
                exchange_label: "事件大纲规划",
                duration_ms: 640,
                first_token_ms: 180,
                model: "gpt-5.4",
              },
            ],
          },
        },
        {
          event_id: "event_json_failed",
          event_type: "model.json_parse_failed",
          stage: "planning",
          message: "JSON 解析失败后已修复",
          created_at: new Date("2026-06-24T00:02:00.000Z").toISOString(),
        },
      ],
    });

    await mockTaskWorkspace(page, workspace);
    await page.route(`**/api/tasks/${taskId}/recover`, async (route) => {
      recoverRequests += 1;
      await route.fulfill({ json: { id: taskId, task_id: taskId, status: "planning" } });
    });

    await page.goto(`/tasks/?id=${taskId}`, { waitUntil: "commit" });
    await page.getByRole("tab", { name: /调试/ }).click();

    await expectVisibleTexts(page, [
      "可恢复异常",
      "请求：2",
      "交换：3",
      "缓存命中：1",
      "JSON 解析失败：1",
      "输入 tokens：1,000",
      "总 tokens：1,280",
      "最新模型：gpt-5.4",
      "大纲规划",
      "轮次：1",
      "审核类型：outline_review",
      "结论：需处理",
      "评分：82",
      "完成 Agent：1",
      "失败 Agent：1",
      "运行记录：2",
      "问题：1",
      "警告：1",
      "自动审核建议人工确认",
      "上下文预算正常。",
      "当前 tokens：1,200",
      "压缩：已启用",
      "响应缓存：命中",
      "缓存片段：3",
      "RAG 已注入",
      "RAG 来源：context_snapshot",
      "最近查询阶段：planning",
      "注入证据：context_snapshot:3",
      "待审核摘要",
      "章节进度",
      "模型调用完成",
      "model.usage 引用",
      "/tasklog/runs/task_debug_rich_fixture/events.tail.json",
    ]);

    await expectNoSensitiveText(page);
    await page.getByRole("button", { name: "打开恢复面板" }).click();
    await expect(page.getByRole("heading", { name: "恢复方案确认" })).toBeVisible();
    await expect(page.getByText("恢复目标：大纲规划")).toBeVisible();
    await expect(page.getByText("默认模型：gpt-5.4")).toBeVisible();
    await expect(page.getByRole("button", { name: "确认执行当前动作" })).toBeEnabled();
    await page.getByRole("button", { name: "确认执行当前动作" }).click();
    await expect.poll(() => recoverRequests, { message: "确认恢复应请求 recover API" }).toBe(1);
  });
});
