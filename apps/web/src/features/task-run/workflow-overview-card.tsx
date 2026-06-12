"use client";

import { useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Stack,
  Typography,
} from "@mui/material";
import {
  AccountTree as WorkflowIcon,
  AutoAwesome as AgentIcon,
  CheckCircle as DoneIcon,
  Error as ErrorIcon,
  HourglassTop as ActiveIcon,
  RadioButtonUnchecked as PendingIcon,
} from "@mui/icons-material";
import type { WorkspaceResponse } from "@/lib/types";
import { buildAgentDispatchGraph, buildWorkflowGraph } from "@/features/task-run/task-run-state.mjs";

type GraphState = "done" | "active" | "pending" | "error";

interface StatusNodeData extends Record<string, unknown> {
  label: string;
  detail?: string;
  kind?: string;
  state: GraphState;
  score?: number;
  issueCount?: number;
  warningCount?: number;
  role?: string;
  invocationKind?: string;
}

function stateColor(state: GraphState): "default" | "primary" | "success" | "warning" | "error" {
  if (state === "done") return "success";
  if (state === "active") return "primary";
  if (state === "error") return "error";
  return "default";
}

function stateLabel(state: GraphState) {
  if (state === "done") return "已完成";
  if (state === "active") return "进行中";
  if (state === "error") return "异常";
  return "待执行";
}

function stateStyles(state: GraphState) {
  if (state === "done") {
    return {
      borderColor: "rgba(46, 125, 91, 0.70)",
      backgroundColor: "rgba(232, 245, 238, 0.94)",
      color: "success.main",
      shadow: "0 8px 20px rgba(46, 125, 91, 0.12)",
    };
  }
  if (state === "active") {
    return {
      borderColor: "rgba(39, 100, 81, 0.85)",
      backgroundColor: "rgba(255, 250, 242, 0.98)",
      color: "primary.main",
      shadow: "0 10px 24px rgba(39, 100, 81, 0.16)",
    };
  }
  if (state === "error") {
    return {
      borderColor: "rgba(180, 74, 63, 0.78)",
      backgroundColor: "rgba(252, 232, 230, 0.96)",
      color: "error.main",
      shadow: "0 8px 20px rgba(180, 74, 63, 0.12)",
    };
  }
  return {
    borderColor: "rgba(29, 42, 39, 0.16)",
    backgroundColor: "rgba(255, 250, 242, 0.86)",
    color: "text.secondary",
    shadow: "0 4px 14px rgba(88,69,37,0.08)",
  };
}

function stateIcon(state: GraphState) {
  if (state === "done") return <DoneIcon fontSize="small" />;
  if (state === "active") return <ActiveIcon fontSize="small" />;
  if (state === "error") return <ErrorIcon fontSize="small" />;
  return <PendingIcon fontSize="small" />;
}

function StatusNode({ data }: NodeProps<Node<StatusNodeData>>) {
  const styles = stateStyles(data.state);
  const isAgent = data.kind && data.kind !== "workflow";

  return (
    <Box
      sx={{
        width: isAgent ? 230 : 190,
        minHeight: isAgent ? 116 : 102,
        px: 1.4,
        py: 1.2,
        border: "2px solid",
        borderColor: styles.borderColor,
        borderRadius: 2,
        backgroundColor: styles.backgroundColor,
        boxShadow: styles.shadow,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Stack spacing={0.75}>
        <Stack direction="row" spacing={0.75} alignItems="center">
          <Box sx={{ display: "grid", placeItems: "center", color: styles.color }}>
            {stateIcon(data.state)}
          </Box>
          <Typography variant="body2" sx={{ fontWeight: 700, color: "text.primary", lineHeight: 1.25 }}>
            {data.label}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          <Chip size="small" color={stateColor(data.state)} label={stateLabel(data.state)} />
          {data.score !== undefined ? <Chip size="small" variant="outlined" label={`${data.score} 分`} /> : null}
          {data.role ? <Chip size="small" variant="outlined" label={data.role} /> : null}
        </Stack>
        {data.detail ? (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
              lineHeight: 1.45,
            }}
          >
            {data.detail}
          </Typography>
        ) : null}
        {(data.issueCount || data.warningCount || data.invocationKind) ? (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {data.issueCount ? <Chip size="small" color="error" variant="outlined" label={`${data.issueCount} 问题`} /> : null}
            {data.warningCount ? <Chip size="small" color="warning" variant="outlined" label={`${data.warningCount} 警告`} /> : null}
            {data.invocationKind ? <Chip size="small" variant="outlined" label={data.invocationKind} /> : null}
          </Stack>
        ) : null}
      </Stack>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  );
}

const nodeTypes = {
  statusNode: StatusNode,
};

function edgeColor(state?: string) {
  if (state === "done") return "#2e7d5b";
  if (state === "active") return "#276451";
  if (state === "error") return "#b44a3f";
  return "rgba(29, 42, 39, 0.28)";
}

function decorateEdges(edges: Edge[]) {
  return edges.map((edge) => {
    const state = typeof edge.data?.state === "string" ? edge.data.state : "pending";
    return {
      ...edge,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: edgeColor(state),
      },
      style: {
        stroke: edgeColor(state),
        strokeWidth: state === "active" ? 3 : 2,
      },
      labelStyle: {
        fill: "#1d2a27",
        fontSize: 12,
        fontWeight: 600,
      },
      labelBgStyle: {
        fill: "#fffaf2",
        fillOpacity: 0.88,
      },
    };
  });
}

function GraphCanvas({
  nodes,
  edges,
  height,
}: {
  nodes: Node<StatusNodeData>[];
  edges: Edge[];
  height: number;
}) {
  return (
    <Box
      sx={{
        height,
        minHeight: height,
        border: "1px solid",
        borderColor: "rgba(29,42,39,0.10)",
        borderRadius: 2,
        overflow: "hidden",
        backgroundColor: "rgba(255, 250, 242, 0.52)",
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={decorateEdges(edges)}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.35}
        maxZoom={1.4}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        panOnScroll
        preventScrolling={false}
      >
        <Background gap={20} color="rgba(29,42,39,0.10)" />
        <MiniMap pannable zoomable nodeStrokeWidth={2} style={{ backgroundColor: "rgba(255,250,242,0.90)" }} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </Box>
  );
}

export default function WorkflowOverviewCard({
  workspace,
}: {
  workspace: WorkspaceResponse;
  onSelectTab?: (tabIndex: number) => void;
}) {
  const workflowGraph = useMemo(() => buildWorkflowGraph(workspace), [workspace]);
  const agentGraph = useMemo(() => buildAgentDispatchGraph(workspace.auto_review_trace ?? []), [workspace.auto_review_trace]);
  const hasAgentGraph = agentGraph.nodes.length > 0;

  return (
    <Card className="glass-card">
      <CardContent sx={{ p: { xs: 2, sm: 2.5 } }}>
        <Stack spacing={2.25}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <WorkflowIcon color="primary" fontSize="small" />
              <Box>
                <Typography variant="h6" sx={{ fontFamily: "var(--font-serif-sc)", lineHeight: 1.2 }}>
                  工作流图谱
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {workflowGraph.summary.message}
                </Typography>
              </Box>
            </Stack>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" color="primary" label={`阶段：${workflowGraph.summary.currentStage || "初始化"}`} />
              {workflowGraph.summary.currentUnit ? <Chip size="small" variant="outlined" label={`单元：${workflowGraph.summary.currentUnit}`} /> : null}
              <Chip size="small" variant="outlined" label={`进度 ${workflowGraph.summary.progress}%`} />
            </Stack>
          </Stack>

          <GraphCanvas
            nodes={workflowGraph.nodes as Node<StatusNodeData>[]}
            edges={workflowGraph.edges as Edge[]}
            height={360}
          />

          <Divider />

          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "flex-start", md: "center" }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <AgentIcon color={hasAgentGraph ? "primary" : "disabled"} fontSize="small" />
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  审核 Agent 派发图
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {hasAgentGraph ? "展示当前审核轮次的主从派发、执行状态和综合裁决。" : "当前工作台暂无可展示的审核 Agent 派发记录。"}
                </Typography>
              </Box>
            </Stack>
            {hasAgentGraph ? (
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip size="small" color="primary" label={`评分 ${agentGraph.summary.score}`} />
                <Chip size="small" variant="outlined" label={`完成 ${agentGraph.summary.completedCount}/${agentGraph.summary.agentCount}`} />
                {agentGraph.summary.failedCount ? <Chip size="small" color="error" variant="outlined" label={`失败 ${agentGraph.summary.failedCount}`} /> : null}
                {agentGraph.summary.traceRound ? <Chip size="small" variant="outlined" label={`第 ${agentGraph.summary.traceRound} 轮`} /> : null}
              </Stack>
            ) : null}
          </Stack>

          {hasAgentGraph ? (
            <GraphCanvas
              nodes={agentGraph.nodes as Node<StatusNodeData>[]}
              edges={agentGraph.edges as Edge[]}
              height={340}
            />
          ) : (
            <Box
              sx={{
                p: 2,
                border: "1px dashed",
                borderColor: "rgba(29,42,39,0.18)",
                borderRadius: 2,
                backgroundColor: "rgba(255,250,242,0.50)",
              }}
            >
              <Typography variant="body2" color="text.secondary">
                自动审核执行后，这里会显示主审核编排 Agent、子 Agent 和综合裁决 Agent 的派发关系。
              </Typography>
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
