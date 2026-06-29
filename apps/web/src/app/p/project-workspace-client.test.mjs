import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { resolveProjectIdFromPathname } from "./project-workspace-client.tsx";

describe("项目工作台客户端路由桥", () => {
  it("从规范项目路径解析真实任务 ID", () => {
    assert.equal(resolveProjectIdFromPathname("/p/task_prod_fixture"), "task_prod_fixture");
    assert.equal(resolveProjectIdFromPathname("/p/task_prod_fixture/"), "task_prod_fixture");
  });

  it("解码路径段并忽略后续路径", () => {
    assert.equal(resolveProjectIdFromPathname("/p/task%20with%20space"), "task with space");
    assert.equal(resolveProjectIdFromPathname("/p/task%2Fwith%2Fslash/logs"), "task/with/slash");
  });

  it("不会把静态导出占位参数当作真实任务 ID", () => {
    assert.equal(resolveProjectIdFromPathname("/p/__placeholder__/"), "");
  });
});
