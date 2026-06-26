// apps/web/e2e/routes.ts
export const routes = {
  // 阶段 1 已存在路由
  home: '/',
  chat: '/chat',
  settings: '/settings',
  archive: '/archive',

  // 旧路由（阶段 2 重定向测试用，阶段 1 不引用）
  legacyTask: (id: string) => `/tasks?id=${id}`,
  legacyReview: (id: string) => `/review?id=${id}`,
  legacyResult: (id: string) => `/result?id=${id}`,
  legacyArchiveDetail: (id: string) => `/archive/detail?id=${id}`,
} as const;

// TODO: 阶段 2 启用的新路由
// export const projectRoutes = {
//   newProject: '/new',
//   project: (id: string) => `/p/${id}`,
//   ...
// };
