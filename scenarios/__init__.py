"""
Scenario package -- auto-registers all tasks on import.

Import this package to populate the global task registry used by the
environment's ``reset(task_id=...)`` mechanism.
"""

from . import easy_disk_full  # noqa: F401
from . import medium_cascading_timeout  # noqa: F401
from . import hard_memory_leak  # noqa: F401
from .registry import TASK_REGISTRY, get_task, list_tasks

__all__ = ["TASK_REGISTRY", "get_task", "list_tasks"]
