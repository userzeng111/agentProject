"use client";

import { Alert, Box, Button, Stack, Typography } from "@mui/material";

export interface PageStateProps {
  title: string | null;
  message?: string;
  error?: string;
  actionLabel?: string;
  actionHref?: string;
  secondaryLabel?: string;
  secondaryHref?: string;
}

export function PageState({ title, message, error, actionLabel, actionHref, secondaryLabel, secondaryHref }: PageStateProps) {
  return (
    <Box sx={{ p: 4, maxWidth: 480, mx: "auto", textAlign: "center" }}>
      <Stack spacing={2.5} alignItems="center">
        <Typography variant="h5">{title}</Typography>
        {error ? <Alert severity="error">{error}</Alert> : null}
        {message ? <Typography color="text.secondary">{message}</Typography> : null}
        <Stack direction="row" spacing={2}>
          {actionLabel && actionHref ? (
            <Button variant="contained" href={actionHref}>{actionLabel}</Button>
          ) : null}
          {secondaryLabel && secondaryHref ? (
            <Button variant="outlined" href={secondaryHref}>{secondaryLabel}</Button>
          ) : null}
        </Stack>
      </Stack>
    </Box>
  );
}
