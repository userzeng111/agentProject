export type TaskMode = "short_story" | "long_story" | "fanfic" | "style_remix";

export type TaskStatus =
  | "created"
  | "waiting_outline_review"
  | "completed"
  | "cancelled"
  | "failed";

export interface ChapterPlan {
  number: number;
  title: string;
  goal: string;
}

export interface StoryPlan {
  working_title: string;
  logline: string;
  world_notes: string[];
  character_notes: string[];
  chapter_plan: ChapterPlan[];
}
