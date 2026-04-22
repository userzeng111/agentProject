import type { ModelOption } from "@/lib/types";

export function isGatewayBackedModel(model?: ModelOption | null): boolean;
export function isNovelTaskModelSupported(model?: ModelOption | null): boolean;
export function selectNovelTaskModels(models?: ModelOption[] | null): ModelOption[];
