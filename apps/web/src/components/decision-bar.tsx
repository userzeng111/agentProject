"use client";

import { AppBar, Button, Toolbar } from "@mui/material";

type DecisionActionColor = "primary" | "error" | "warning" | "secondary";
type DecisionActionVariant = "contained" | "outlined";

interface DecisionAction {
  label: string;
  onClick: () => void;
  variant?: DecisionActionVariant;
  color?: DecisionActionColor;
  disabled?: boolean;
}

interface DecisionBarProps {
  actions: DecisionAction[];
}

export function DecisionBar({ actions }: DecisionBarProps) {
  return (
    <AppBar
      position="sticky"
      color="default"
      elevation={0}
      sx={{
        top: "auto",
        bottom: 0,
        zIndex: (theme) => theme.zIndex.appBar + 50,
        backgroundColor: "background.paper",
        borderTop: "1px solid",
        borderColor: "custom.border",
      }}
    >
      <Toolbar sx={{ justifyContent: "flex-end", gap: 2, px: { xs: 2, md: 3 } }}>
        {actions.map((action, index) => (
          <Button
            key={index}
            variant={action.variant ?? "outlined"}
            color={action.color ?? "primary"}
            disabled={action.disabled}
            onClick={action.onClick}
          >
            {action.label}
          </Button>
        ))}
      </Toolbar>
    </AppBar>
  );
}

export type { DecisionAction };
