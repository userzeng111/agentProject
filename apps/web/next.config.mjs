import {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
  PHASE_PRODUCTION_SERVER,
} from "next/constants.js";

export default function createNextConfig(phase) {
  const isDevelopmentServer = phase === PHASE_DEVELOPMENT_SERVER;
  const isProductionPhase =
    phase === PHASE_PRODUCTION_BUILD || phase === PHASE_PRODUCTION_SERVER;

  /** @type {import('next').NextConfig} */
  const nextConfig = {
    reactStrictMode: true,
    distDir: isDevelopmentServer ? ".next-dev" : ".next",
    ...(isProductionPhase ? { output: "export" } : {}),
    trailingSlash: true,
    images: {
      unoptimized: true,
    },
  };

  return nextConfig;
}
