"use client";

import { Box, Button, IconButton, List, ListItemButton, ListItemText, ListItemIcon, Tooltip, Typography } from "@mui/material";
import { Add as AddIcon, ChatBubbleOutline as ChatIcon, Delete as DeleteIcon } from "@mui/icons-material";

const SIDEBAR_WIDTH = 280;

export default function ChatSessionSidebar({
  conversations,
  currentConvId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
}: {
  conversations: Array<{ id: string; title: string; updatedAt: number }>;
  currentConvId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onDeleteConversation: (id: string) => void;
}) {
  return (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", bgcolor: "background.default" }}>
      <Box sx={{ p: 2 }}>
        <Button variant="outlined" startIcon={<AddIcon />} size="small" fullWidth onClick={onNewConversation}>
          新对话
        </Button>
      </Box>

      <List sx={{ flex: 1, overflowY: "auto", px: 1 }} aria-label="会话列表">
        {conversations.length > 0 ? (
          conversations.map((conv) => (
            <ListItemButton
              key={conv.id}
              selected={conv.id === currentConvId}
              onClick={() => onSelectConversation(conv.id)}
              sx={{ borderRadius: 2, mb: 0.25 }}
            >
              <ListItemIcon sx={{ minWidth: 36 }}>
                <ChatIcon fontSize="small" color={conv.id === currentConvId ? "primary" : "inherit"} />
              </ListItemIcon>
              <ListItemText
                primary={conv.title || "新对话"}
                secondary={new Date(conv.updatedAt).toLocaleString()}
                primaryTypographyProps={{ noWrap: true, variant: "body2", fontWeight: conv.id === currentConvId ? 600 : 400 }}
                secondaryTypographyProps={{ noWrap: true, variant: "caption" }}
              />
              <Tooltip title="删除会话">
                <IconButton
                  size="small"
                  aria-label="删除会话"
                  onClick={(e) => { e.stopPropagation(); onDeleteConversation(conv.id); }}
                  sx={{ opacity: 0.5, "&:hover": { opacity: 1 } }}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </ListItemButton>
          ))
        ) : (
          <Box sx={{ p: 2, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              暂无会话记录
            </Typography>
          </Box>
        )}
      </List>
    </Box>
  );
}

export { SIDEBAR_WIDTH };
