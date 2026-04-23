import test from "node:test";
import assert from "node:assert/strict";

import {
  getCurrentTraceRound,
  inferExecutionKind,
  splitTraceRounds,
  summarizeTraceRound,
} from "./trace-rounds.mjs";

const trace = [
  { __summary__: true, overall_score: 61, review_type: "outline_review", trace_round: 1 },
  { agent_id: "main-1", role: "orchestrator", execution_kind: "main_agent", status: "completed" },
  { agent_id: "sub-1", role: "structure", execution_kind: "subagent", status: "completed", score: 66 },
  { agent_id: "syn-1", role: "synthesis", execution_kind: "synthesis", status: "completed", score: 61 },
  { __summary__: true, overall_score: 72, review_type: "chapter_pair_review", trace_round: 2, batch_index: 2 },
  { agent_id: "main-2", role: "orchestrator", execution_kind: "main_agent", status: "completed" },
  { agent_id: "sub-2", role: "style", execution_kind: "subagent", status: "completed", score: 74 },
  { agent_id: "sub-3", role: "consistency", execution_kind: "subagent", status: "failed", score: 0 },
  { agent_id: "syn-2", role: "synthesis", execution_kind: "synthesis", status: "completed", score: 72 },
];

test("splitTraceRounds 按 summary 分段历史 trace", () => {
  const rounds = splitTraceRounds(trace);
  assert.equal(rounds.length, 2);
  assert.equal(rounds[0].entries.length, 3);
  assert.equal(rounds[1].entries.length, 4);
});

test("getCurrentTraceRound 返回最后一轮", () => {
  const currentRound = getCurrentTraceRound(trace);
  assert.equal(currentRound.summary.review_type, "chapter_pair_review");
  assert.equal(currentRound.summary.trace_round, 2);
});

test("summarizeTraceRound 只统计当前轮次主从数量", () => {
  const summary = summarizeTraceRound(getCurrentTraceRound(trace));
  assert.equal(summary.mainAgents.length, 1);
  assert.equal(summary.subAgents.length, 2);
  assert.equal(summary.synthesisAgents.length, 1);
  assert.equal(summary.completedCount, 2);
  assert.equal(summary.failedCount, 1);
  assert.equal(summary.displayScore, 72);
});

test("inferExecutionKind 对旧 trace 保持兼容", () => {
  assert.equal(inferExecutionKind({ role: "orchestrator" }), "main_agent");
  assert.equal(inferExecutionKind({ role: "synthesis" }), "synthesis");
  assert.equal(inferExecutionKind({ role: "structure" }), "subagent");
});
