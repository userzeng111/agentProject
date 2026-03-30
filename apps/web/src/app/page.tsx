"use client";

import AutoStoriesRoundedIcon from "@mui/icons-material/AutoStoriesRounded";
import HubRoundedIcon from "@mui/icons-material/HubRounded";
import LayersRoundedIcon from "@mui/icons-material/LayersRounded";
import { Button, Card, CardContent, Chip, Container, Stack, Typography } from "@mui/material";
import Link from "next/link";

export default function Home() {
  return (
    <Container maxWidth="lg" sx={{ py: { xs: 6, md: 10 } }}>
      <Stack spacing={4}>
        <Stack spacing={2}>
          <Chip label="LangChain + LangGraph + GPT-5.4" sx={{ alignSelf: "flex-start" }} />
          <Typography
            variant="h2"
            sx={{
              fontFamily: "var(--font-serif-sc)",
              maxWidth: 760,
              lineHeight: 1.12,
            }}
          >
            输入一个创意，先过大纲审核，再生成可读的小说初稿。
          </Typography>
          <Typography variant="h6" color="text.secondary" sx={{ maxWidth: 760 }}>
            这个 demo 展示了双运行时架构：Next.js 负责界面和任务流，FastAPI + LangGraph 负责工作流编排，
            并支持在大纲阶段人工确认后继续生成正文。
          </Typography>
        </Stack>

        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <Button component={Link} href="/create" size="large" variant="contained">
            创建一个新任务
          </Button>
          <Button component={Link} href="/create" size="large" variant="outlined">
            直接体验短篇 / 长篇 / 同人 / 风格复刻
          </Button>
        </Stack>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: 24,
          }}
        >
          {[
            {
              icon: <HubRoundedIcon />,
              title: "工作流先规划后写作",
              text: "先做需求标准化与故事规划，再在 review 页确认大纲，避免直接把长文本塞进一个不可控的大模型请求里。",
            },
            {
              icon: <LayersRoundedIcon />,
              title: "前后端彻底分层",
              text: "Web 层只处理任务创建、状态展示和人工审核；Runtime 层只处理 LangGraph 的节点执行和状态恢复。",
            },
            {
              icon: <AutoStoriesRoundedIcon />,
              title: "支持参考文本输入",
              text: "你可以上传一个 UTF-8 文本文件，demo 会把它作为世界观或风格参考，但不会把原文直接拼贴进输出。",
            },
          ].map((item) => (
            <Card key={item.title} sx={{ borderRadius: 4 }}>
              <CardContent>
                <Stack spacing={2}>
                  <div
                    style={{
                      width: 48,
                      height: 48,
                      borderRadius: 16,
                      display: "grid",
                      placeItems: "center",
                      backgroundColor: "rgba(39, 100, 81, 0.1)",
                      color: "#276451",
                    }}
                  >
                    {item.icon}
                  </div>
                  <Typography variant="h5" sx={{ fontFamily: "var(--font-serif-sc)" }}>
                    {item.title}
                  </Typography>
                  <Typography color="text.secondary">{item.text}</Typography>
                </Stack>
              </CardContent>
            </Card>
          ))}
        </div>
      </Stack>
    </Container>
  );
}
