# Contributing to Agent Memory Engine

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
pytest
python benchmark/run_benchmark.py --k 5
```

Install `.[hybrid]` only when working on semantic retrieval.

## Where changes belong

- Core use cases: `agent_memory_engine/service.py`
- Storage contracts/backends: `agent_memory_engine/storage/`
- Retrieval/ranking: `agent_memory_engine/retrieval/`
- Framework integrations: `adapters/<framework>/`
- Evaluation data/tools: `benchmark/`
- Architectural decisions and plans: `docs/`

The engine must not import an adapter or agent-framework SDK.

## Change requirements

Every change should include:

1. tests for behavior and failure paths;
2. benchmark comparison for retrieval/ranking changes;
3. migration and compatibility notes for schema/configuration changes;
4. timeout, fallback, and data-loss analysis for external dependencies;
5. documentation that distinguishes implemented behavior from future design.

Do not log raw memory content by default. Do not add network/model dependencies
to the baseline installation. Keep outputs bounded before placing them in agent
context.

## Compatibility

New code should use `agent_memory_engine`, `agent-memory`, and
`AGENT_MEMORY_*`. The `pi-memory` command and `PI_MEMORY_*` settings are
transitional aliases and should not be expanded with new Pi-specific behavior.

## Pull-request checklist

- [ ] Unit/integration tests pass.
- [ ] `git diff --check` passes.
- [ ] Benchmark impact is recorded when relevant.
- [ ] New persisted fields have migration coverage.
- [ ] Security and tenant/workspace scope were considered.
- [ ] Documentation and examples were updated.
