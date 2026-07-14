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
import { useTheme } from "@mui/material/styles";
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
type ThemeMode = "light" | "dark";

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

function stateStyles(state: GraphState, mode: ThemeMode) {
  if (mode === "dark") {
    if (state === "done") {
      return {
        borderColor: "rgba(76, 175, 132, 0.72)",
        backgroundColor: "rgba(15, 59, 45, 0.96)",
        color: "success.light",
        shadow: "0 10px 24px rgba(0, 0, 0, 0.34)",
      };
    }
    if (state === "active") {
      return {
        borderColor: "rgba(115, 191, 150, 0.86)",
        backgroundColor: "rgba(18, 69, 54, 0.98)",
        color: "primary.light",
        shadow: "0 12px 28px rgba(34, 197, 94, 0.18)",
      };
    }
    if (state === "error") {
      return {
        borderColor: "rgba(244, 118, 102, 0.78)",
        backgroundColor: "rgba(87, 34, 32, 0.96)",
        color: "error.light",
        shadow: "0 10px 24px rgba(0, 0, 0, 0.36)",
      };
    }
    return {
      borderColor: "rgba(148, 163, 184, 0.32)",
      backgroundColor: "rgba(18, 25, 33, 0.94)",
      color: "text.secondary",
      shadow: "0 8px 20px rgba(0, 0, 0, 0.28)",
    };
  }

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
  const theme = useTheme();
  const styles = stateStyles(data.state, theme.palette.mode);
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

function edgeColor(state: string | undefined, mode: ThemeMode) {
  if (mode === "dark") {
    if (state === "done") return "#73bf96";
    if (state === "active") return "#8fd9ad";
    if (state === "error") return "#f47666";
    return "rgba(148, 163, 184, 0.42)";
  }
  if (state === "done") return "#2e7d5b";
  if (state === "active") return "#276451";
  if (state === "error") return "#b44a3f";
  return "rgba(29, 42, 39, 0.28)";
}

function decorateEdges(edges: Edge[], mode: ThemeMode) {
  const labelFill = mode === "dark" ? "#e8f5ee" : "#1d2a27";
  const labelBgFill = mode === "dark" ? "#101821" : "#fffaf2";
  return edges.map((edge) => {
    const state = typeof edge.data?.state === "string" ? edge.data.state : "pending";
    const color = edgeColor(state, mode);
    return {
      ...edge,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color,
      },
      style: {
        stroke: color,
        strokeWidth: state === "active" ? 3 : 2,
      },
      labelStyle: {
        fill: labelFill,
        fontSize: 12,
        fontWeight: 600,
      },
      labelBgStyle: {
        fill: labelBgFill,
        fillOpacity: mode === "dark" ? 0.92 : 0.88,
      },
    };
  });
}

function GraphCanvas({
  nodes,
  edges,
  height,
  label,
}: {
  nodes: Node<StatusNodeData>[];
  edges: Edge[];
  height: number;
  label: string;
}) {
  const theme = useTheme();
  const mode = theme.palette.mode;
  const canvasStyles =
    mode === "dark"
      ? {
          borderColor: "rgba(148, 163, 184, 0.22)",
          backgroundColor: "rgba(2, 6, 23, 0.58)",
          backgroundColorGrid: "rgba(148, 163, 184, 0.18)",
          miniMapBg: "rgba(15, 23, 42, 0.94)",
          miniMapMask: "rgba(2, 6, 23, 0.58)",
          miniMapNode: "rgba(34, 197, 94, 0.36)",
          miniMapStroke: "rgba(203, 213, 225, 0.72)",
        }
      : {
          borderColor: "rgba(29,42,39,0.10)",
          backgroundColor: "rgba(255, 250, 242, 0.52)",
          backgroundColorGrid: "rgba(29,42,39,0.10)",
          miniMapBg: "rgba(255,250,242,0.90)",
          miniMapMask: "rgba(255,250,242,0.36)",
          miniMapNode: "rgba(46, 125, 91, 0.30)",
          miniMapStroke: "rgba(29,42,39,0.46)",
        };

  return (
    <Box
      role="region"
      aria-label={label}
      sx={{
        height,
        minHeight: height,
        width: "100%",
        maxWidth: "100%",
        minWidth: 0,
        border: "1px solid",
        borderColor: canvasStyles.borderColor,
        borderRadius: 2,
        overflow: "hidden",
        contain: "layout paint",
        backgroundColor: canvasStyles.backgroundColor,
      }}
    >
      <ReactFlow
        nodes={nodes}
        edges={decorateEdges(edges, mode)}
        nodeTypes={nodeTypes}
        colorMode={mode}
        aria-label={label}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        minZoom={0.18}
        maxZoom={1.4}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        panOnScroll
        preventScrolling={false}
      >
        <Background gap={20} color={canvasStyles.backgroundColorGrid} />
        <MiniMap
          pannable
          zoomable
          nodeStrokeWidth={2}
          bgColor={canvasStyles.miniMapBg}
          maskColor={canvasStyles.miniMapMask}
          nodeColor={canvasStyles.miniMapNode}
          nodeStrokeColor={canvasStyles.miniMapStroke}
        />
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
    <Card
      className="glass-card"
      data-testid="workflow-overview-card"
      sx={(theme) => ({
        backgroundColor:
          theme.palette.mode === "dark"
            ? "rgba(15, 23, 21, 0.82)"
            : "rgba(255, 250, 242, 0.65)",
        border: "1px solid",
        borderColor:
          theme.palette.mode === "dark"
            ? "rgba(168, 160, 149, 0.18)"
            : "rgba(255, 255, 255, 0.45)",
        boxShadow:
          theme.palette.mode === "dark"
            ? "0 12px 32px rgba(0, 0, 0, 0.34)"
            : "0 8px 24px rgba(0, 0, 0, 0.12)",
      })}
    >
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
            label="工作流图谱画布"
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
              label="审核 Agent 派发图画布"
            />
          ) : (
            <Box
              sx={{
                p: 2,
                border: "1px dashed",
                borderColor: (theme) =>
                  theme.palette.mode === "dark" ? "rgba(148, 163, 184, 0.28)" : "rgba(29,42,39,0.18)",
                borderRadius: 2,
                backgroundColor: (theme) =>
                  theme.palette.mode === "dark" ? "rgba(15, 23, 42, 0.64)" : "rgba(255,250,242,0.50)",
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
