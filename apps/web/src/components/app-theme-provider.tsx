"use client";

import { CssBaseline, ThemeProvider, createTheme, type Shadows } from "@mui/material";
import { useMemo } from "react";
import { ThemeModeProvider, useThemeMode } from "./theme-mode-provider";

const LIGHT_TOKENS = {
  bgDefault: "#F7EFE2",
  bgPaper: "#FFFAF2",
  bgElevated: "#FFFFFF",
  textPrimary: "#1A1612",
  textSecondary: "#5C5348",
  border: "#E5D9C8",
};

const DARK_TOKENS = {
  bgDefault: "#0F1412",
  bgPaper: "#1A211E",
  bgElevated: "#242E2A",
  textPrimary: "#F2EEE8",
  textSecondary: "#A8A095",
  border: "#3A4540",
};

function getShadows(mode: "light" | "dark"): Shadows {
  const alpha = mode === "light" ? "0.08" : "0.35";
  const xlAlpha = mode === "light" ? "0.16" : "0.50";
  return [
    "none",
    `0 1px 2px rgba(0,0,0,${alpha})`,
    `0 2px 4px rgba(0,0,0,${alpha})`,
    `0 3px 6px rgba(0,0,0,${alpha})`,
    `0 4px 12px rgba(0,0,0,${alpha})`,
    `0 5px 14px rgba(0,0,0,${alpha})`,
    `0 6px 16px rgba(0,0,0,${alpha})`,
    `0 7px 18px rgba(0,0,0,${alpha})`,
    `0 8px 24px rgba(0,0,0,${alpha})`,
    `0 9px 26px rgba(0,0,0,${alpha})`,
    `0 10px 28px rgba(0,0,0,${alpha})`,
    `0 11px 30px rgba(0,0,0,${alpha})`,
    `0 12px 32px rgba(0,0,0,${alpha})`,
    `0 13px 34px rgba(0,0,0,${alpha})`,
    `0 14px 36px rgba(0,0,0,${alpha})`,
    `0 15px 38px rgba(0,0,0,${alpha})`,
    `0 16px 48px rgba(0,0,0,${xlAlpha})`,
    `0 17px 50px rgba(0,0,0,${xlAlpha})`,
    `0 18px 52px rgba(0,0,0,${xlAlpha})`,
    `0 19px 54px rgba(0,0,0,${xlAlpha})`,
    `0 20px 56px rgba(0,0,0,${xlAlpha})`,
    `0 21px 58px rgba(0,0,0,${xlAlpha})`,
    `0 22px 60px rgba(0,0,0,${xlAlpha})`,
    `0 23px 62px rgba(0,0,0,${xlAlpha})`,
    `0 24px 64px rgba(0,0,0,${xlAlpha})`,
  ];
}

export function getDesignTokens(mode: "light" | "dark") {
  const tokens = mode === "light" ? LIGHT_TOKENS : DARK_TOKENS;
  const shadows = getShadows(mode);
  return {
    palette: {
      mode,
      primary: {
        main: mode === "light" ? "#276451" : "#4FD1A8",
        light: mode === "light" ? "#3a8a70" : "#6EE6C0",
        dark: mode === "light" ? "#1E4D3E" : "#1E4D3E",
      },
      secondary: {
        main: mode === "light" ? "#9A5F2F" : "#D4A574",
        light: mode === "light" ? "#b87a48" : "#E8C99E",
      },
      background: {
        default: tokens.bgDefault,
        paper: tokens.bgPaper,
      },
      text: {
        primary: tokens.textPrimary,
        secondary: tokens.textSecondary,
      },
      success: { main: "#2e7d5b", light: "#e8f5ee" },
      warning: { main: "#D68A1E", light: "#fef3e6" },
      error: { main: "#C0392B", light: "#fce8e6" },
      info: { main: "#4a7a8a", light: "#e6f0f3" },
      custom: {
        bgDefault: tokens.bgDefault,
        bgPaper: tokens.bgPaper,
        bgElevated: tokens.bgElevated,
        textPrimary: tokens.textPrimary,
        textSecondary: tokens.textSecondary,
        border: tokens.border,
      },
    },
    shape: { borderRadius: 10 },
    shadows,
    typography: {
      fontFamily: "var(--font-sans-sc)",
      h1: { fontFamily: "var(--font-serif-sc)" },
      h2: { fontFamily: "var(--font-serif-sc)" },
      h3: { fontFamily: "var(--font-serif-sc)" },
      h4: { fontFamily: "var(--font-serif-sc)" },
      h5: { fontFamily: "var(--font-serif-sc)" },
      h6: { fontFamily: "var(--font-serif-sc)" },
    },
    components: {
      MuiCard: {
        styleOverrides: {
          root: {
            border: `1px solid ${tokens.border}`,
            boxShadow: shadows[4],
            borderRadius: 16,
            padding: 24,
            transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
            backgroundColor: tokens.bgPaper,
          },
        },
      },
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 10,
            textTransform: "none",
            paddingInline: 20,
            paddingBlock: 10,
            fontWeight: 500,
            transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
          },
          contained: {
            boxShadow: shadows[2],
            "&:hover": { boxShadow: shadows[4] },
            "&:active": { boxShadow: shadows[1] },
          },
          outlined: {
            borderColor: tokens.border,
            "&:hover": {
              borderColor: mode === "light" ? "#276451" : "#4FD1A8",
              backgroundColor: mode === "light" ? "rgba(39, 100, 81, 0.05)" : "rgba(79, 209, 168, 0.08)",
            },
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            fontWeight: 500,
          },
        },
      },
      MuiTextField: {
        styleOverrides: {
          root: {
            "& .MuiOutlinedInput-root": {
              borderRadius: 10,
              transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
            },
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 16,
            backgroundImage: "none",
          },
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper: {
            borderRadius: 16,
            boxShadow: shadows[16],
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            borderRadius: 8,
            backgroundColor: mode === "light" ? "#1A1612" : "#F2EEE8",
            color: mode === "light" ? "#F2EEE8" : "#1A1612",
          },
        },
      },
      MuiDivider: {
        styleOverrides: {
          root: {
            borderColor: tokens.border,
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: "none",
            fontWeight: 500,
            fontSize: "0.95rem",
            minHeight: 48,
            color: tokens.textSecondary,
            "&.Mui-selected": {
              color: mode === "light" ? "#276451" : "#4FD1A8",
              fontWeight: 600,
            },
          },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: {
            backgroundColor: mode === "light" ? "#276451" : "#4FD1A8",
            height: 2,
            borderRadius: 1,
          },
        },
      },
      MuiPaginationItem: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            fontWeight: 500,
            "&.Mui-selected": {
              backgroundColor: mode === "light" ? "#276451" : "#4FD1A8",
              color: "#fff",
              "&:hover": {
                backgroundColor: mode === "light" ? "#1E4D3E" : "#6EE6C0",
              },
            },
          },
        },
      },
    },
  };
}

function ThemeProviderInner({ children }: { children: React.ReactNode }) {
  const { resolvedMode } = useThemeMode();
  const theme = useMemo(
    () => createTheme(getDesignTokens(resolvedMode)),
    [resolvedMode]
  );

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </ThemeProvider>
  );
}

export function AppThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <ThemeModeProvider>
      <ThemeProviderInner>{children}</ThemeProviderInner>
    </ThemeModeProvider>
  );
}
