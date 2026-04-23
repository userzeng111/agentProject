export function isTraceSummaryEntry(item) {
  return Boolean(item && item.__summary__);
}

export function inferExecutionKind(agent) {
  if (
    agent?.execution_kind === "main_agent" ||
    agent?.execution_kind === "subagent" ||
    agent?.execution_kind === "synthesis"
  ) {
    return agent.execution_kind;
  }
  if (agent?.role === "orchestrator") return "main_agent";
  if (agent?.role === "synthesis") return "synthesis";
  return "subagent";
}

export function splitTraceRounds(trace) {
  const rounds = [];
  let currentSummary = null;
  let currentEntries = [];

  const flush = () => {
    if (!currentSummary && currentEntries.length === 0) {
      return;
    }
    rounds.push({
      summary: currentSummary,
      entries: [...currentEntries],
      round: rounds.length + 1,
    });
    currentSummary = null;
    currentEntries = [];
  };

  for (const item of trace || []) {
    if (!item) continue;
    if (isTraceSummaryEntry(item)) {
      flush();
      currentSummary = item;
      continue;
    }
    currentEntries.push(item);
  }

  flush();
  return rounds;
}

export function getCurrentTraceRound(trace) {
  const rounds = splitTraceRounds(trace);
  if (rounds.length === 0) {
    return {
      summary: null,
      entries: [],
      round: 0,
    };
  }
  return rounds[rounds.length - 1];
}

export function summarizeTraceRound(traceRound) {
  const agentItems = traceRound?.entries || [];
  const summaryEntry = traceRound?.summary || null;
  const hasStructuredExecution = agentItems.some(
    (agent) => Boolean(agent?.execution_kind) || agent?.role === "orchestrator" || Boolean(agent?.parent_agent_id)
  );
  const mainAgents = agentItems.filter((agent) => inferExecutionKind(agent) === "main_agent");
  const subAgents = agentItems.filter((agent) => inferExecutionKind(agent) === "subagent");
  const synthesisAgents = agentItems.filter((agent) => inferExecutionKind(agent) === "synthesis");
  const trackedAgents = hasStructuredExecution
    ? agentItems.filter((agent) => inferExecutionKind(agent) !== "main_agent")
    : agentItems;
  const completedAgents = trackedAgents.filter((agent) => agent?.status === "completed");
  const completedCount = completedAgents.length;
  const failedCount = trackedAgents.filter((agent) => agent?.status === "failed").length;
  let displayScore = 0;
  if (typeof summaryEntry?.overall_score === "number") {
    displayScore = Math.round(summaryEntry.overall_score);
  } else if (completedAgents.length > 0) {
    const total = completedAgents.reduce((sum, agent) => sum + (agent?.score ?? 0), 0);
    displayScore = Math.round(total / completedAgents.length);
  }

  return {
    summaryEntry,
    agentItems,
    hasStructuredExecution,
    mainAgents,
    subAgents,
    synthesisAgents,
    trackedAgents,
    completedCount,
    failedCount,
    displayScore,
  };
}
