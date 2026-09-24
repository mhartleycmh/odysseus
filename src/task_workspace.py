"""Workspace binding for scheduled LLM tasks."""

import os

class TaskWorkspaceError(ValueError):
    """A task must stop rather than fall back after losing its workspace."""


def validate_task_workspace(raw, owner, task_type="llm", *, persisted=False):
    if raw is None or raw == "":
        return None
    from src.tool_execution import vet_workspace
    from src.tool_security import owner_is_admin_or_single_user

    if not owner_is_admin_or_single_user(owner):
        raise PermissionError("Only admins may bind a task workspace")
    if task_type != "llm":
        raise TaskWorkspaceError("Workspace is supported only for LLM tasks")
    resolved = vet_workspace(raw)
    if not resolved:
        raise TaskWorkspaceError("Scheduled task workspace is invalid")
    # Stored paths are canonical. Reject replacement by a link to a new tree.
    if persisted and os.path.normcase(resolved) != os.path.normcase(raw):
        raise TaskWorkspaceError("Scheduled task workspace has changed")
    return resolved
