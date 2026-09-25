"""Does a CMH pilot allowlist really close every dispatchable tool?

The restricted-task policy is built as ``known_tool_names() - allowed_tools``
and handed to the executor as a DENYLIST. That only holds while every name the
executor can dispatch is in ``known_tool_names()`` — the docstring of which
says "best-effort". These tests measure the surface instead of trusting it.
"""
import ast
import asyncio
import json
from pathlib import Path

import pytest

from src.tool_policy import ToolPolicy, known_tool_names

ROOT = Path(__file__).resolve().parents[1]
PILOT_ALLOWLIST = {"read_file", "ls", "grep", "glob"}


def pilot_policy():
    """The exact policy src/task_scheduler.py builds for a restricted task."""
    blocked = known_tool_names() - PILOT_ALLOWLIST
    return ToolPolicy(disabled_tools=frozenset(blocked), hidden_tools=frozenset(blocked),
                      disable_mcp=True), blocked


def dispatch_literals():
    """Tool names the executor's dispatch chain compares against, via AST."""
    tree = ast.parse((ROOT / "src" / "tool_execution.py").read_text(encoding="utf-8"))
    names = set()

    def literal_of(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        return set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id != "tool":
            continue
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.In)):
                names |= literal_of(comparator)
    # The fixed legacy map is data, not a literal comparison.
    from src.tool_execution import _MCP_TOOL_MAP
    names |= set(_MCP_TOOL_MAP)
    return names


# `json` and `xml` are not dispatch branches: they appear only in the
# misformatted-tool-call hint (`tool in ("python", "json", "xml")`), and the
# chain ends at the "Unknown tool" arm for them. Asserted below, not assumed.
PARSER_HINTS = {"json", "xml"}


def test_every_directly_dispatchable_tool_is_denied_by_the_pilot_allowlist():
    _, blocked = pilot_policy()
    reachable = dispatch_literals()
    assert reachable, "found no dispatch literals — the AST walk broke"
    escapes = sorted(name for name in reachable
                     if name not in PILOT_ALLOWLIST and name not in blocked and name not in PARSER_HINTS)
    assert escapes == [], (
        f"{len(escapes)} of {len(reachable)} dispatchable tools are neither allowed "
        f"nor denied for a restricted task: {escapes}"
    )


@pytest.mark.parametrize("tool", sorted(PARSER_HINTS))
def test_the_parser_hints_reach_no_handler(tool):
    """They are exempt from the check above only because nothing dispatches them."""
    from src import tool_execution
    _, blocked = pilot_policy()
    desc, result = asyncio.run(tool_execution.execute_tool_block(
        type("Block", (), {"tool_type": tool, "content": "texto suelto"})(),
        disabled_tools=set(blocked), owner="admin",
        security_context=tool_execution.NO_TOOL_SECURITY_CONTEXT,
    ))
    assert desc.startswith("unknown:"), (desc, result)
    assert result.get("exit_code") == 1


def test_shell_and_python_are_denied():
    _, blocked = pilot_policy()
    for name in ("bash", "python", "write_file", "apply_patch", "web_fetch", "web_search"):
        assert name in blocked, f"{name} is not denied by the pilot allowlist"


@pytest.mark.parametrize("tool", [
    "mcp__memory__manage_memory",      # a builtin server that IS registered
    "mcp__rag__manage_rag",
    "mcp__image_gen__generate_image",
    "mcp__totally__invented",
])
def test_a_guessed_mcp_name_never_reaches_the_mcp_manager(monkeypatch, tool):
    """disable_mcp must hold at execution time, not only in the prompt.

    agent_loop drops its own manager when the policy says so, but the executor
    fetches the process-wide manager itself, and a denylist built from
    known_tool_names() can never list a qualified mcp__server__tool name.

    The owner is forced admin on purpose: an independent check of this
    installation found the six restricted CMH tasks are owned by an admin
    account with auth enabled, so the is_public_blocked_tool guard does NOT
    stop them. Without that, this test would pass for the wrong reason.
    """
    from src import tool_execution

    called = []

    class _Manager:
        async def call_tool(self, name, args):
            called.append(name)
            return {"output": "escaped", "exit_code": 0}

    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: _Manager())
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    policy, blocked = pilot_policy()
    desc, result = asyncio.run(tool_execution.execute_tool_block(
        type("Block", (), {"tool_type": tool, "content": "{}"})(),
        disabled_tools=set(blocked),
        owner="admin",
        tool_policy=policy,
        security_context=tool_execution.NO_TOOL_SECURITY_CONTEXT,
    ))
    assert called == [], f"the restricted task reached MCP tool {called}"
    assert result.get("exit_code") == 1, result
    assert "BLOCKED" in desc, (desc, result)


def test_an_unrestricted_turn_still_reaches_mcp():
    """The fix must not disable MCP for everyone: only a policy that asked."""
    from src.tool_policy import ToolPolicy
    assert ToolPolicy().blocks("mcp__memory__manage_memory") is False
    assert ToolPolicy(disable_mcp=True).blocks("mcp__memory__manage_memory") is True
    # The pilot's own read tools are unaffected by the MCP clamp.
    assert ToolPolicy(disable_mcp=True).blocks("read_file") is False


def scheduler_policy(allowlist):
    """Rebuild exactly what src/task_scheduler.py hands the executor."""
    from src.tool_policy import ToolPolicy
    from src.tool_security import email_tool_policy_names
    blocked = known_tool_names() - allowlist
    allowed_mcp = {name for tool in allowlist for name in email_tool_policy_names(tool)
                   if name.startswith("mcp__")}
    return ToolPolicy(disabled_tools=frozenset(blocked), hidden_tools=frozenset(blocked),
                      disable_mcp=True, allowed_mcp_names=frozenset(allowed_mcp)), blocked


def run_tool(tool, allowlist, monkeypatch):
    from src import tool_execution
    called = []

    class _Manager:
        async def call_tool(self, name, args):
            called.append(name)
            return {"output": "ran", "exit_code": 0}

    monkeypatch.setattr(tool_execution, "get_mcp_manager", lambda: _Manager())
    monkeypatch.setattr(tool_execution, "_owner_is_admin", lambda owner: True)
    policy, blocked = scheduler_policy(allowlist)
    desc, result = asyncio.run(tool_execution.execute_tool_block(
        type("Block", (), {"tool_type": tool, "content": "{}"})(),
        disabled_tools=set(blocked), owner="admin", tool_policy=policy,
        security_context=tool_execution.NO_TOOL_SECURITY_CONTEXT,
    ))
    return desc, result, called


@pytest.mark.parametrize("tool", ["send_email", "mcp__email__send_email"])
def test_the_mcp_clamp_never_vetoes_what_the_allowlist_permits(monkeypatch, tool):
    """Regression: every email tool is allowlistable AND aliases to an
    mcp__email__ name, so a blanket MCP clamp silently blocked a tool the
    prompt still offered to the model."""
    assert "send_email" in known_tool_names(), "send_email must stay allowlistable"
    desc, result, called = run_tool(tool, {"send_email", "read_file", "ls"}, monkeypatch)
    assert "BLOCKED" not in desc, (desc, result)
    assert result.get("exit_code") == 0, result


def test_an_email_tool_outside_the_allowlist_is_still_blocked(monkeypatch):
    desc, result, called = run_tool("send_email", PILOT_ALLOWLIST, monkeypatch)
    assert "BLOCKED" in desc, (desc, result)
    assert called == []


def test_allowing_email_does_not_reopen_other_mcp_servers(monkeypatch):
    """The exception is per-name, not a blanket re-enable."""
    desc, result, called = run_tool("mcp__memory__manage_memory",
                                    {"send_email", "read_file"}, monkeypatch)
    assert "BLOCKED" in desc, (desc, result)
    assert called == []


def test_the_block_message_names_the_real_reason(monkeypatch):
    """It used to claim a guide-only policy for every block, which is wrong."""
    desc, result, called = run_tool("mcp__memory__manage_memory", PILOT_ALLOWLIST, monkeypatch)
    assert "guide-only" not in result.get("error", ""), result
    assert "MCP" in result.get("error", ""), result


def test_the_scheduler_still_builds_the_policy_this_test_assumes():
    """Guard the coupling: if the scheduler stops using a denylist, revisit."""
    source = (ROOT / "src" / "task_scheduler.py").read_text(encoding="utf-8")
    assert "blocked = known_tool_names() - allowed_tools" in source
    assert "disable_mcp=True" in source
    assert "allowed_mcp_names=frozenset(allowed_mcp)" in source
