"use client";

import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: "#276451",
      light: "#3a8a70",
      dark: "#1d4d3d",
    },
    secondary: {
      main: "#9a5f2f",
      light: "#b87a48",
    },
    background: {
      default: "#efe4cf",
      paper: "#fffaf2",
    },
    text: {
      primary: "#1d2a27",
      secondary: "rgba(29, 42, 39, 0.72)",
    },
    success: {
      main: "#2e7d5b",
      light: "#e8f5ee",
    },
    warning: {
      main: "#c47a2a",
      light: "#fef3e6",
    },
    error: {
      main: "#b44a3f",
      light: "#fce8e6",
    },
    info: {
      main: "#4a7a8a",
      light: "#e6f0f3",
    },
  },
  shape: {
    borderRadius: 12,
  },
  shadows: [
    "none",
    "0 2px 8px rgba(88,69,37,0.12)",
    "0 4px 20px rgba(88,69,37,0.10)",
    "0 8px 32px rgba(88,69,37,0.12)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
    "0 16px 48px rgba(88,69,37,0.15)",
  ],
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
          border: "1px solid rgba(29, 42, 39, 0.08)",
          boxShadow: "0 4px 20px rgba(88,69,37,0.10)",
          borderRadius: 16,
          padding: 24,
          transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          textTransform: "none",
          paddingInline: 20,
          paddingBlock: 10,
          fontWeight: 500,
          transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
        },
        contained: {
          boxShadow: "0 2px 8px rgba(88,69,37,0.18)",
          "&:hover": {
            boxShadow: "0 4px 16px rgba(88,69,37,0.22)",
          },
          "&:active": {
            boxShadow: "0 1px 4px rgba(88,69,37,0.15)",
          },
        },
        outlined: {
          borderColor: "rgba(29, 42, 39, 0.18)",
          "&:hover": {
            borderColor: "#276451",
            backgroundColor: "rgba(39, 100, 81, 0.05)",
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
            borderRadius: 12,
            transition: "all 0.2s cubic-bezier(0.4, 0, 0.2, 1)",
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 16,
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: 16,
          boxShadow: "0 16px 48px rgba(88,69,37,0.15)",
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          borderRadius: 8,
          backgroundColor: "#1d2a27",
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: "rgba(29, 42, 39, 0.08)",
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
          color: "text.secondary",
          "&.Mui-selected": {
            color: "primary.main",
            fontWeight: 600,
          },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: {
          backgroundColor: "primary.main",
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
            backgroundColor: "primary.main",
            color: "#fff",
            "&:hover": {
              backgroundColor: "primary.dark",
            },
          },
        },
      },
    },
  },
});

export function AppThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </ThemeProvider>
  );
}
