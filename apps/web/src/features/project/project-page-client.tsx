"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Typography } from "@mui/material";
import { ApiRequestError, getWorkspace } from "@/lib/api";
import { WorkspaceMeta } from "@/lib/types";
import { normalizeView, resolveProjectAccess, resolveProjectId } from "./project-state.mjs";
import { ProjectShell } from "@/components/project-shell";
import { PageState } from "@/components/page-state";
import TaskRunClient from "@/features/task-run/task-run-client";
import TaskReviewClient from "@/features/task-review/task-review-client";
import TaskResultClient from "@/features/task-result/task-result-client";
import ArchiveDetailClient from "@/features/task-archive/archive-detail-client";
import { homeHref, workspaceHref, projectViewHref } from "@/lib/task-routes";

export default function ProjectPageClient() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [projectId, setProjectId] = useState<string | null>(null);
  const [meta, setMeta] = useState<WorkspaceMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<Error | null>(null);

  // 解析 project ID
  useEffect(() => {
    const id = resolveProjectId(window.location.pathname || pathname || "");
    setProjectId(id);
  }, [pathname]);

  // 解析 view
  const rawView = searchParams.get("view");
  const view = normalizeView(rawView);

  // 规范化 URL：?view=workspace → 无查询参数
  useEffect(() => {
    if (!projectId) return;
    if (view === "workspace" && rawView) {
      router.replace(workspaceHref(projectId));
      return;
    }
  }, [projectId, view, rawView, router]);

  // 读取工作台数据
  const fetchWorkspace = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    setFetchError(null);
    try {
      const data = await getWorkspace(id);
      setMeta(data?.meta ?? null);
    } catch (reason) {
      setMeta(null);
      setFetchError(reason instanceof Error ? reason : new Error("读取项目数据失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (projectId) fetchWorkspace(projectId);
  }, [projectId, view, fetchWorkspace]);

  /* ── 渲染逻辑 ── */

  if (projectId === null) return null;

  if (!projectId) {
    return <PageState title="项目地址无效" message="无法从当前地址解析项目 ID" actionLabel="返回作品库" actionHref={homeHref()} />;
  }

  if (rawView && view === null) {
    return <PageState title="项目视图不存在" message={`"${rawView}" 不是有效视图`} actionLabel="返回项目工作台" actionHref={workspaceHref(projectId)} />;
  }

  if (loading) {
    return (
      <ProjectShell breadcrumbs={[{ label: "作品库", href: homeHref() }, { label: projectId }]} title={projectId}>
        <Typography color="text.secondary" sx={{ p: 2, textAlign: "center" }} role="status" aria-live="polite">加载中...</Typography>
      </ProjectShell>
    );
  }

  if (fetchError instanceof ApiRequestError && fetchError.status === 404) {
    return <PageState title="项目不存在或已删除" actionLabel="返回作品库" actionHref={homeHref()} />;
  }

  if (fetchError) {
    return <PageState title="读取项目失败" error={fetchError.message} actionLabel="重试" actionHref={workspaceHref(projectId)} secondaryLabel="返回作品库" secondaryHref={homeHref()} />;
  }

  if (!meta) {
    return <PageState title="项目不存在或已删除" actionLabel="返回作品库" actionHref={homeHref()} />;
  }

  const access = resolveProjectAccess(meta);

  // 审核视图 —— 直接渲染 TaskReviewClient
  if (view === "review") {
    if (!access.canViewReview) {
      return (
        <ProjectShell breadcrumbs={[{ label: "作品库", href: homeHref() }, { label: meta.title || projectId, href: workspaceHref(projectId) }, { label: "审核" }]} title={meta.title || projectId}>
          <PageState title={access.reviewBlockReason} actionLabel="返回项目工作台" actionHref={workspaceHref(projectId)} />
        </ProjectShell>
      );
    }
    return <TaskReviewClient taskId={projectId} />;
  }

  // 结果视图 —— 直接渲染 TaskResultClient
  if (view === "result") {
    if (!access.canViewResult) {
      return (
        <ProjectShell breadcrumbs={[{ label: "作品库", href: homeHref() }, { label: meta.title || projectId, href: workspaceHref(projectId) }, { label: "结果" }]} title={meta.title || projectId}>
          {meta.status === "completed"
            ? <PageState title="任务已完成" message="确认归档后可查看归档视图" actionLabel="查看结果" actionHref={projectViewHref(projectId, "result")} secondaryLabel="返回工作台" secondaryHref={workspaceHref(projectId)} />
            : <PageState title={access.resultBlockReason} actionLabel="返回项目工作台" actionHref={workspaceHref(projectId)} />
          }
        </ProjectShell>
      );
    }
    return <TaskResultClient taskId={projectId} />;
  }

  // 归档视图 —— 直接渲染 ArchiveDetailClient
  if (view === "archive") {
    if (!access.canViewArchive) {
      return (
        <ProjectShell breadcrumbs={[{ label: "作品库", href: homeHref() }, { label: meta.title || projectId, href: workspaceHref(projectId) }, { label: "归档" }]} title={meta.title || projectId}>
          {meta.status === "completed"
            ? <PageState title={access.archiveBlockReason} actionLabel="查看结果" actionHref={projectViewHref(projectId, "result")} />
            : <PageState title={access.archiveBlockReason} actionLabel="返回项目工作台" actionHref={workspaceHref(projectId)} />
          }
        </ProjectShell>
      );
    }
    return <ArchiveDetailClient taskId={projectId} />;
  }

  // 默认：工作台视图
  return <TaskRunClient taskId={projectId} />;
}
