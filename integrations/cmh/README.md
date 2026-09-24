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

This confines native file tools; it does not sandbox shell, Python, MCP, or
other external tools. The pilot still needs an enforced tool allowlist and
separate verification of its no-overwrite rule before it can run as specified.

Validation: 134 tests passed and 10 were skipped across task workspace/API,
tool availability, session delivery, cancellation, owner scope, and path
confinement. No live model calls or server restart were performed.
Two additional migration checks passed for existing nullable schemas and
legacy table rebuilds, including repeat execution without data loss.

The `cmh-researcher` task must remain paused until a dry run is performed with
synthetic input and its run ID, effective workspace, tool calls, output, and
blocked escape attempts are recorded. Do not widen access to financial or
production folders based on the prompt alone.
