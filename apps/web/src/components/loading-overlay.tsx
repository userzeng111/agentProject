"use client";

import { Backdrop, CircularProgress, Typography } from "@mui/material";

interface LoadingOverlayProps {
  open: boolean;
  message?: string;
}

export function LoadingOverlay({ open, message }: LoadingOverlayProps) {
  return (
    <Backdrop
      open={open}
      sx={{
        zIndex: (theme) => theme.zIndex.modal + 1,
        display: "flex",
        flexDirection: "column",
        gap: 2,
        backgroundColor: "rgba(0, 0, 0, 0.25)",
      }}
    >
      <CircularProgress color="primary" />
      {message && (
        <Typography variant="body2" color="white">
          {message}
        </Typography>
      )}
    </Backdrop>
  );
}
