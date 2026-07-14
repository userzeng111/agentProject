import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  archiveListHref,
  chatHref,
  homeHref,
  newProjectHref,
  projectViewHref,
  settingsHref,
  workspaceHref,
  legacyProjectHref,
  legacyCreateHref,
} from "./task-routes.ts";

describe("任务路由工具函数", () => {
  describe("homeHref", () => {
    it("返回作品库首页", () => {
      assert.equal(homeHref(), "/");
    });
  });

  describe("workspaceHref", () => {
    it("生成带尾斜杠作品工作台规范链接", () => {
      assert.equal(workspaceHref("task-123"), "/p/task-123/");
      assert.equal(workspaceHref("abc-def-456"), "/p/abc-def-456/");
    });

    it("按路径段编码特殊字符", () => {
      assert.equal(workspaceHref("task with spaces"), "/p/task%20with%20spaces/");
      assert.equal(workspaceHref("task/with/slashes"), "/p/task%2Fwith%2Fslashes/");
      assert.equal(workspaceHref("task?with=query"), "/p/task%3Fwith%3Dquery/");
    });

    it("处理空字符串", () => {
      assert.equal(workspaceHref(""), "/p//");
    });
  });

  describe("newProjectHref", () => {
    it("返回带尾斜杠新建作品规范路径", () => {
      assert.equal(newProjectHref(), "/new/");
    });
  });

  describe("projectViewHref", () => {
    it("生成审核视图链接", () => {
      assert.equal(projectViewHref("task-123", "review"), "/p/task-123/?view=review");
    });

    it("生成结果视图链接", () => {
      assert.equal(projectViewHref("abc-456", "result"), "/p/abc-456/?view=result");
    });

    it("生成归档视图链接（默认无 tab）", () => {
      assert.equal(projectViewHref("t-1", "archive"), "/p/t-1/?view=archive");
    });

    it("生成归档视图链接（合法 tab）", () => {
      assert.equal(projectViewHref("t-1", "archive", { tab: "read" }), "/p/t-1/?view=archive&tab=read");
      assert.equal(projectViewHref("t-1", "archive", { tab: "overview" }), "/p/t-1/?view=archive&tab=overview");
      assert.equal(projectViewHref("t-1", "archive", { tab: "outline" }), "/p/t-1/?view=archive&tab=outline");
      assert.equal(projectViewHref("t-1", "archive", { tab: "meta" }), "/p/t-1/?view=archive&tab=meta");
    });

    it("忽略归档视图非法 tab", () => {
      assert.equal(projectViewHref("t-1", "archive", { tab: "invalid" }), "/p/t-1/?view=archive");
    });

    it("非归档视图忽略 tab 参数", () => {
      // projectViewHref 是 TS 函数但由 tsx 转译，传递额外 tab 测试忽略逻辑
      const result = projectViewHref("t-1", "review", { tab: "read" });
      assert.equal(result, "/p/t-1/?view=review");
    });
  });

  describe("archiveListHref", () => {
    it("返回归档列表规范路径", () => {
      assert.equal(archiveListHref(), "/archive/");
    });
  });

  describe("chatHref", () => {
    it("返回聊天规范路径", () => {
      assert.equal(chatHref(), "/chat/");
    });
  });

  describe("settingsHref", () => {
    it("返回设置规范路径", () => {
      assert.equal(settingsHref(), "/settings/");
    });
  });

  describe("legacyProjectHref", () => {
    it("映射 /tasks/ 到工作台", () => {
      assert.equal(
        legacyProjectHref("/tasks/", new URLSearchParams("id=task-123")),
        "/p/task-123/",
      );
    });

    it("映射 /review/ 到审核视图", () => {
      assert.equal(
        legacyProjectHref("/review/", new URLSearchParams("id=abc456")),
        "/p/abc456/?view=review",
      );
    });

    it("映射 /result/ 到结果视图", () => {
      assert.equal(
        legacyProjectHref("/result/", new URLSearchParams("id=task-x")),
        "/p/task-x/?view=result",
      );
    });

    it("映射 /archive/detail/ 到归档视图（合法 tab）", () => {
      assert.equal(
        legacyProjectHref("/archive/detail/", new URLSearchParams("id=t1&tab=read")),
        "/p/t1/?view=archive&tab=read",
      );
    });

    it("映射 /archive/detail/ 默认 overview（无 tab）", () => {
      assert.equal(
        legacyProjectHref("/archive/detail/", new URLSearchParams("id=t1")),
        "/p/t1/?view=archive&tab=overview",
      );
    });

    it("映射 /archive/detail/ 默认 overview（非法 tab）", () => {
      assert.equal(
        legacyProjectHref("/archive/detail/", new URLSearchParams("id=t1&tab=invalid")),
        "/p/t1/?view=archive&tab=overview",
      );
    });

    it("未知来源路径返回 null", () => {
      assert.equal(legacyProjectHref("/unknown/", new URLSearchParams("id=t1")), null);
    });

    it("缺失 ID 返回 null", () => {
      assert.equal(legacyProjectHref("/tasks/", new URLSearchParams("")), null);
    });

    it("编码特殊字符", () => {
      assert.equal(
        legacyProjectHref("/tasks/", new URLSearchParams("id=task with spaces")),
        "/p/task%20with%20spaces/",
      );
    });
  });

  describe("legacyCreateHref", () => {
    it("保留查询参数跳转", () => {
      assert.equal(
        legacyCreateHref(new URLSearchParams("retry_from=t1&model=m1")),
        "/new/?retry_from=t1&model=m1",
      );
    });

    it("无参数时返回简洁路径", () => {
      assert.equal(legacyCreateHref(new URLSearchParams("")), "/new/");
    });
  });
});
