# End-to-end demonstration

This demonstration shows a project convention surviving a complete agent
restart. It exercises the framework-neutral Agent Memory Engine through its Pi
adapter. Pi-specific lifecycle translation stays in `adapters/pi/`; persistence,
retrieval, and context construction stay in the Python engine.

## Session A: capture a convention

Start Pi with the extension:

```bash
export AGENT_MEMORY_PATH="$PWD/.agent-memory.json"
pi -e "$PWD/adapters/pi/extension.ts"
```

Tell the agent:

```text
Please remember that this project uses pnpm, not npm, and that the test command
is pnpm test.
```

The agent calls `remember`; the adapter invokes `agent-memory capture`; and the
result is persisted as a JSON observation. Exit Pi completely after the tool
call finishes.

## Session B: retrieve without repeating the answer

Launch the same command again to create a fresh session, then ask:

```text
@memory How do I run the tests for this project?
```

Prefix a question with `@memory` to make the adapter retrieve related memories
before the agent starts and inject the stored convention. The prefix is removed
before the question reaches the agent. The agent can answer `pnpm test` without
asking the user to restate it, while unmarked questions skip retrieval.

```mermaid
sequenceDiagram
    participant U as User
    participant P as Pi agent
    participant M as Memory engine
    participant J as JSON store
    U->>P: Remember: use pnpm; tests run with pnpm test
    P->>M: remember(summary, tags)
    M->>J: atomic persist
    Note over U,P: Process exits; a new session starts
    U->>P: @memory How do I run the tests?
    P->>M: inject(query, budget=2000)
    M->>J: load observations
    M-->>P: Relevant memory: use pnpm test
    P-->>U: Run pnpm test
```

## CLI-only smoke test

The storage and retrieval path can also be verified without installing Pi:

```bash
export AGENT_MEMORY_PATH="$PWD/.agent-memory.json"
python -m agent_memory_engine.cli capture \
  --summary "This project uses pnpm; run tests with pnpm test" \
  --tags "tooling,testing"
python -m agent_memory_engine.cli inject \
  --query "How do I run the tests?" \
  --budget 500
```

For a portfolio-ready recording, run the two sessions above in a clean terminal
and capture both the `remember` tool call and the fresh-session answer.
