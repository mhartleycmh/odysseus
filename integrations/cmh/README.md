# CMH integration boundary

This integration keeps Odysseus as the visual and execution platform while
preserving CMH's vault rules. It is intentionally limited to the first pilot
agent and does not grant access to the financial source folders.

## Pilot workspace

The pilot agent may use only:

```text
CMH_Claude/odysseus/data/agent_workspace/cmh-researcher/
  input/
  working/
  output/
```

The agent must not read or write:

- `Base Matriz Nueva/`
- `Modelo Financiero Nuevo/`
- `Dashboard Financiero/`
- `CMH_Canon/`
- any `fuentes/` directory

Those folders remain outside the pilot until a separate approval policy is
implemented and tested.

## Pilot workflow

```text
researcher -> evidence note -> verifier -> human approval
```

The pilot can prepare a research note and list open questions. It cannot
approve an executive deliverable, send email, execute shell commands, or
overwrite an existing file.

## Provider policy

Odysseus remains provider-neutral. Claude and OpenAI credentials are configured
inside its authenticated Settings surface and are never stored in this
integration directory. Provider calls must be attributable to an Odysseus
user/session and appear in the application logs.

## Implementation status

Scheduled LLM tasks now persist a vetted `workspace` path and propagate it through
the scheduler, agent loop, and file-tool resolver. Invalid or deleted
workspaces are rejected at task execution time, and the resolver remains
confined to the task workspace for that run. Windows path handling also
recognizes both `/` and `\` separators for the sensitive-path deny list.

Only an admin (or the existing single-user mode) may assign a workspace.
The API rejects workspaces on action/research tasks until those execution
paths support the same binding. Pass `workspace` on task creation or update;
an empty string clears it on update, while an omitted/null field preserves
the current value. Stored paths are canonical and revalidated at execution,
including owner privileges. A missing or redirected directory stops the run
without a fallback model call. Workspace-bound assistant check-ins use the
ordinary agent loop rather than collecting integration data directly.

Scheduled LLM tasks may now carry an `allowed_tools` list. When present, every
native tool outside the list and all MCP tools are disabled for that run. The
pilot is configured with only `glob`, `grep`, `ls`, and `read_file`, so it has
no file-writing, shell, Python, email, or external-tool capability through
the agent loop. Restricted tasks fail rather than falling back to an untraced
LLM call. This is an application-level policy, not an operating-system sandbox;
the synthetic live run and blocked-escape evidence are still required.

Validation: 134 tests passed and 10 were skipped across task workspace/API,
tool availability, session delivery, cancellation, owner scope, and path
confinement. No live model calls or server restart were performed.
Two additional migration checks passed for existing nullable schemas and
legacy table rebuilds, including repeat execution without data loss.

### Workflows and memory proposals (2026-09-24, not yet run against a provider)

`/cmh` builds the CMH chain investigador → constructor → verificador →
revisor → documentador as a persistent DAG. Each step snapshots its agent,
model, endpoint, instructions version, workspace and read-only tools, and
stores exactly one artifact; the reviewer receives the builder's and the
verifier's artifacts, never reasoning, and must be a different agent from the
builder. Runs survive restarts and stop/resume without repeating a finished
step; events are replayable over SSE with `Last-Event-ID`.

A restricted step fails instead of storing text Odysseus wrote itself (empty
response, stream error, forced synthesis, round cap, escalation to another
model). No agent workspace may lie in or contain `Base Matriz Nueva/`,
`Modelo Financiero Nuevo/`, `Dashboard Financiero/`, `Producción/`,
`CMH_Canon/` (master or mirror) or any `fuentes/` folder.

Memory proposals edit the canon master and project cards outside financial
and production folders only after a diff preview and explicit approval, with a
backup, an atomic write and restore. The canon mirror in
`CMH_Claude/CMH_Canon/` follows only when it held exactly the replaced bytes.

The `cmh-researcher` task remains paused until a dry run records its run ID,
effective workspace, tool calls, output, and blocked escape attempts. See
`ESTADO_AGENTIC_OS.md` for the current checkpoint. Do not widen access to
financial or production folders based on the prompt alone.

## Agentic OS web interface (`/cmh/os`)

A second, fuller view lives at `/cmh/os` (`static/cmh-os/`): overview,
orchestration graph driven by run events, executions, human approvals, memory,
tools and MCP, observability, evaluations, security and settings, plus a
coordinator chat. It reads the same admin APIs as `/cmh` and adds no write
path of its own; without an admin session it shows labelled demo data. The
original `/cmh` view is unchanged. How to run and verify it:
`integrations/cmh/docs/README.md`.
