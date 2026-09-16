# Agent adapters

Adapters translate framework lifecycle events and tools into Agent Memory Engine
operations. They must remain thin: memory schema, ranking, persistence, and
lifecycle policy belong in `agent_memory_engine/`.

Each adapter should document:

- supported framework/version;
- capture and retrieval triggers;
- timeout and graceful-degradation behavior;
- tenant/workspace/session identity mapping;
- installation and end-to-end verification;
- whether injected content persists in the framework conversation.

Current adapter: [`pi/extension.ts`](pi/extension.ts).
