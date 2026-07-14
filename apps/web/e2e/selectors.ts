// apps/web/e2e/selectors.ts
export const selectors = {
  appHeader: {
    root: '[data-testid="app-header"]',
    searchInput: '[data-testid="global-search-input"]',
    chatLink: '[data-testid="chat-link"]',
    settingsLink: '[data-testid="settings-link"]',
  },
  home: {
    newProjectButton: '[data-testid="new-project-button"]',
    projectCard: '[data-testid="project-card"]',
    viewToggle: '[data-testid="view-toggle"]',
  },
  common: {
    confirmDialog: '[data-testid="confirm-dialog"]',
    confirmButton: '[data-testid="confirm-button"]',
    cancelButton: '[data-testid="cancel-button"]',
    notification: '[data-testid="notification"]',
  },
} as const;

// TODO: 阶段 2 新增选择器
// export const newProjectSelectors = { ... };
// export const workspaceSelectors = { ... };
