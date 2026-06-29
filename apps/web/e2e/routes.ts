// apps/web/e2e/routes.ts
export const routes = {
  // 阶段 1 已存在路由
  home: '/',
  newProject: '/new',
  chat: '/chat',
  settings: '/settings',
  archive: '/archive',
  project: (id: string) => `/p/${id}`,

  // 旧路由（阶段 2 重定向测试用，阶段 1 不引用）
  legacyCreate: (query = "") => `/create${query ? `?${query}` : ""}`,
  legacyTask: (id: string) => `/tasks?id=${id}`,
  legacyReview: (id: string) => `/review?id=${id}`,
  legacyResult: (id: string) => `/result?id=${id}`,
  legacyArchiveDetail: (id: string) => `/archive/detail?id=${id}`,
} as const;
