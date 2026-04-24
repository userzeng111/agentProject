"""工作流引擎模块。

提供 NovelWorkflowEngine（LangGraph 工作流执行引擎）和 WorkflowCallbacks（节点回调注册表），
将工作流编排与业务实现解耦。
"""

from app.workflow.callbacks import WorkflowCallbacks
from app.workflow.engine import NovelWorkflowEngine

__all__ = ["WorkflowCallbacks", "NovelWorkflowEngine"]
