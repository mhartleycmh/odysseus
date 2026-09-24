"""Workspace binding for scheduled LLM tasks."""

import os
import json

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


def validate_task_tools(raw, owner, task_type="llm", *, persisted=False):
    """Return a vetted native-tool allowlist, or None for legacy task behavior."""
    if raw is None:
        return None
    from src.tool_policy import known_tool_names
    from src.tool_security import owner_is_admin_or_single_user

    if not owner_is_admin_or_single_user(owner):
        raise PermissionError("Only admins may set task tools")
    if task_type != "llm":
        raise TaskWorkspaceError("Tool allowlists are supported only for LLM tasks")
    if persisted:
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise TaskWorkspaceError("Stored task tool policy is invalid") from exc
    if not isinstance(raw, list) or any(not isinstance(t, str) for t in raw):
        raise TaskWorkspaceError("Task tools must be a list of names")
    names = set(raw)
    if len(names) != len(raw) or not names <= known_tool_names():
        raise TaskWorkspaceError("Task tool list contains duplicates or unknown tools")
    return names
