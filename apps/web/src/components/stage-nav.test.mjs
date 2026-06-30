import { describe, it } from "node:test";
import assert from "node:assert";

describe("StageNav", () => {
  it("resolves done, current and upcoming states from the active step", async () => {
    const { resolveStageNavItems } = await import("./stage-nav");

    const items = resolveStageNavItems(
      [
        { label: "创建" },
        { label: "审核" },
        { label: "结果" },
      ],
      1,
    );

    assert.deepStrictEqual(
      items.map((item) => item.state),
      ["done", "current", "upcoming"],
    );
    assert.strictEqual(items[1].ariaCurrent, "step");
  });

  it("clamps active step to the available stage range", async () => {
    const { resolveStageNavItems } = await import("./stage-nav");
    const stages = [{ label: "创建" }, { label: "结果" }];

    assert.deepStrictEqual(
      resolveStageNavItems(stages, -5).map((item) => item.state),
      ["current", "upcoming"],
    );
    assert.deepStrictEqual(
      resolveStageNavItems(stages, 99).map((item) => item.state),
      ["done", "current"],
    );
  });
});
