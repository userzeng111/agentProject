"use client";

import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: "#276451",
    },
    secondary: {
      main: "#9a5f2f",
    },
    background: {
      default: "#efe4cf",
      paper: "#fffaf2",
    },
    text: {
      primary: "#1d2a27",
      secondary: "rgba(29, 42, 39, 0.72)",
    },
  },
  shape: {
    borderRadius: 20,
  },
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
          boxShadow: "0 18px 48px rgba(88, 69, 37, 0.08)",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          textTransform: "none",
          paddingInline: 18,
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
