import type { CreativeMode, NovelSize, TaskMode } from "@/lib/types";

const CREATIVE_MODE_LABELS: Record<CreativeMode, string> = {
  original: "全新原创",
  fanfic: "同人创作",
  style_remix: "风格复刻",
};

const NOVEL_SIZE_LABELS: Record<NovelSize, string> = {
  short: "短篇",
  medium: "中篇",
  long: "长篇",
};

const LEGACY_MODE_TO_CREATIVE: Record<TaskMode, CreativeMode> = {
  short_story: "original",
  long_story: "original",
  fanfic: "fanfic",
  style_remix: "style_remix",
};

const LEGACY_MODE_TO_SIZE: Record<TaskMode, NovelSize> = {
  short_story: "short",
  long_story: "long",
  fanfic: "medium",
  style_remix: "long",
};

export function resolveCreativeMode(creativeMode?: CreativeMode, mode?: TaskMode): CreativeMode {
  if (creativeMode) {
    return creativeMode;
  }
  return mode ? LEGACY_MODE_TO_CREATIVE[mode] : "original";
}

export function resolveNovelSize(novelSize?: NovelSize, mode?: TaskMode): NovelSize {
  if (novelSize) {
    return novelSize;
  }
  return mode ? LEGACY_MODE_TO_SIZE[mode] : "short";
}

export function formatCreativeModeLabel(creativeMode?: CreativeMode, mode?: TaskMode): string {
  return CREATIVE_MODE_LABELS[resolveCreativeMode(creativeMode, mode)];
}

export function formatNovelSizeLabel(novelSize?: NovelSize, mode?: TaskMode): string {
  return NOVEL_SIZE_LABELS[resolveNovelSize(novelSize, mode)];
}

export function formatTaskTypeLabel(input: {
  creativeMode?: CreativeMode;
  novelSize?: NovelSize;
  mode?: TaskMode;
}): string {
  return `${formatCreativeModeLabel(input.creativeMode, input.mode)} · ${formatNovelSizeLabel(input.novelSize, input.mode)}`;
}

export function needsStyleProfile(creativeMode?: CreativeMode, mode?: TaskMode): boolean {
  const resolved = resolveCreativeMode(creativeMode, mode);
  return resolved === "fanfic" || resolved === "style_remix";
}
