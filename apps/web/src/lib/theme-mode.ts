export type ThemeMode = "light" | "dark" | "system";

export const STORAGE_KEY = "theme-mode";

export function getInitialMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}
