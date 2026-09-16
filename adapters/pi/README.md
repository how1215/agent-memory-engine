# Pi adapter

This adapter maps Pi lifecycle events to Agent Memory Engine CLI operations.
It is intentionally thin and fail-open: memory failures do not block the agent.

## Run

```bash
export AGENT_MEMORY_PATH="$PWD/.agent-memory.json"
pi -e "$PWD/adapters/pi/extension.ts"
```

- The `remember` tool invokes `agent_memory_engine.cli capture`.
- A prompt prefixed with `@memory` invokes retrieval during
  `before_agent_start`; the prefix is removed before the model sees the prompt.
- An unmarked prompt does not start retrieval or append a new memory block.
- Injected blocks are persistent Pi session messages, so earlier blocks remain
  in later context.

Set `AGENT_MEMORY_PYTHON` when the adapter should use a particular interpreter.
`PYTHON` remains a fallback.

## Known limitations and planned work

The adapter currently uses synchronous `spawnSync` without an explicit timeout.
Planned hardening includes asynchronous execution, cancellation, timeout and
output limits, structured content-safe diagnostics, workspace identity, and an
adapter smoke-test harness. Memory policy must remain in the engine rather than
being duplicated here.
