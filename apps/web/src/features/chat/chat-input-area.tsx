"use client";

import { Box, IconButton, Paper, TextField } from "@mui/material";
import { CircularProgress } from "@mui/material";
import { Send as SendIcon } from "@mui/icons-material";

export default function ChatInputArea({
  value,
  onChange,
  onSend,
  loading,
  canSend,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  loading?: boolean;
  canSend: boolean;
}) {
  const sendDisabled = Boolean(loading) || !(value || "").trim() || !canSend;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!sendDisabled) {
        onSend();
      }
    }
  };

  return (
    <Box sx={{ p: { xs: 1.25, sm: 2 }, borderTop: "1px solid", borderColor: "divider" }}>
      <Paper
        variant="outlined"
        sx={{
          p: 1,
          display: "flex",
          alignItems: "flex-end",
          gap: 1,
          borderRadius: 3,
          minWidth: 0,
        }}
      >
        <TextField
          multiline
          maxRows={6}
          size="small"
          placeholder="输入消息，按回车发送..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={loading}
          sx={{
            flex: 1,
            minWidth: 0,
            "& .MuiOutlinedInput-root": { bgcolor: "transparent" },
            "& .MuiOutlinedInput-notchedOutline": { border: "none" },
          }}
        />
        <IconButton
          color="primary"
          onClick={onSend}
          aria-label="发送消息"
          disabled={sendDisabled}
          sx={{ flexShrink: 0 }}
        >
          {loading ? <CircularProgress size={20} color="inherit" /> : <SendIcon />}
        </IconButton>
      </Paper>
    </Box>
  );
}
