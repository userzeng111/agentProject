from __future__ import annotations

from app.application.task_service.core import TaskServiceCoreMixin
from app.application.task_service.recovery import TaskServiceRecoveryMixin
from app.application.task_service.review import TaskServiceReviewMixin
from app.application.task_service.continuation import TaskServiceContinuationMixin
from app.application.task_service.runner import TaskServiceRunnerMixin
from app.application.task_service.queries import TaskServiceQueriesMixin


class TaskService(
    TaskServiceQueriesMixin,
    TaskServiceRunnerMixin,
    TaskServiceContinuationMixin,
    TaskServiceReviewMixin,
    TaskServiceRecoveryMixin,
    TaskServiceCoreMixin,
):
    """任务服务门面，组合所有功能 mixin。"""
    pass
