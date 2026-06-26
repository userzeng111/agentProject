import localFont from "next/font/local";

export const sourceHanSerif = localFont({
  // 路径相对于调用 localFont 的文件（src/lib/fonts.ts）
  // src/lib/fonts.ts → public/fonts/... 为 ../../public/fonts/...
  src: [
    {
      path: "../../public/fonts/source-han-serif-cn-400-subset.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/source-han-serif-cn-600-subset.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-serif-sc",
  display: "swap",
  fallback: ["Songti SC", "SimSun", "serif"],
});

export const sourceHanSans = localFont({
  src: [
    {
      path: "../../public/fonts/source-han-sans-cn-400-subset.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../public/fonts/source-han-sans-cn-500-subset.woff2",
      weight: "500",
      style: "normal",
    },
  ],
  variable: "--font-sans-sc",
  display: "swap",
  fallback: ["PingFang SC", "Microsoft YaHei", "sans-serif"],
});
