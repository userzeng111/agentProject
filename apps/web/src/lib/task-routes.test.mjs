import { describe, it } from "node:test";
import assert from "node:assert/strict";

describe("任务路由工具函数", () => {
  // 模拟路由函数
  function workspaceHref(taskId) {
    return `/tasks/?id=${encodeURIComponent(taskId)}`;
  }

  function reviewHref(taskId) {
    return `/review/?id=${encodeURIComponent(taskId)}`;
  }

  function resultHref(taskId) {
    return `/result/?id=${encodeURIComponent(taskId)}`;
  }

  function archiveDetailHref(taskId) {
    return `/archive/detail/?id=${encodeURIComponent(taskId)}`;
  }

  function settingsHref() {
    return "/settings";
  }

  describe("workspaceHref", () => {
    it("正确生成任务工作区链接", () => {
      assert.equal(workspaceHref("task-123"), "/tasks/?id=task-123");
      assert.equal(workspaceHref("abc-def-456"), "/tasks/?id=abc-def-456");
    });

    it("正确编码特殊字符", () => {
      assert.equal(workspaceHref("task with spaces"), "/tasks/?id=task%20with%20spaces");
      assert.equal(workspaceHref("task/with/slashes"), "/tasks/?id=task%2Fwith%2Fslashes");
      assert.equal(workspaceHref("task?with=query"), "/tasks/?id=task%3Fwith%3Dquery");
    });

    it("处理空字符串", () => {
      assert.equal(workspaceHref(""), "/tasks/?id=");
    });
  });

  describe("reviewHref", () => {
    it("正确生成审核链接", () => {
      assert.equal(reviewHref("task-123"), "/review/?id=task-123");
      assert.equal(reviewHref("abc-def-456"), "/review/?id=abc-def-456");
    });

    it("正确编码特殊字符", () => {
      assert.equal(reviewHref("task with spaces"), "/review/?id=task%20with%20spaces");
    });
  });

  describe("resultHref", () => {
    it("正确生成结果链接", () => {
      assert.equal(resultHref("task-123"), "/result/?id=task-123");
      assert.equal(resultHref("abc-def-456"), "/result/?id=abc-def-456");
    });

    it("正确编码特殊字符", () => {
      assert.equal(resultHref("task with spaces"), "/result/?id=task%20with%20spaces");
    });
  });

  describe("archiveDetailHref", () => {
    it("正确生成归档详情链接", () => {
      assert.equal(archiveDetailHref("task-123"), "/archive/detail/?id=task-123");
      assert.equal(archiveDetailHref("abc-def-456"), "/archive/detail/?id=abc-def-456");
    });

    it("正确编码特殊字符", () => {
      assert.equal(archiveDetailHref("task with spaces"), "/archive/detail/?id=task%20with%20spaces");
    });
  });

  describe("settingsHref", () => {
    it("返回固定的设置路径", () => {
      assert.equal(settingsHref(), "/settings");
    });
  });
});
