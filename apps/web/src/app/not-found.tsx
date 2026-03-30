import Link from "next/link";
import { Box, Button, Container, Stack, Typography } from "@mui/material";

export default function NotFound() {
  return (
    <Box component="main">
      <Container maxWidth="sm" sx={{ py: 10 }}>
        <Stack spacing={3} alignItems="flex-start">
          <Typography variant="h2" sx={{ fontFamily: "var(--font-serif-sc)" }}>
            这个页面不存在
          </Typography>
          <Typography color="text.secondary">
            你访问的任务页可能已经失效，或者路径输入有误。
          </Typography>
          <Button component={Link} href="/" variant="contained">
            返回首页
          </Button>
        </Stack>
      </Container>
    </Box>
  );
}
