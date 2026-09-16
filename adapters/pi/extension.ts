// Adapter between Pi's extension API and the Python memory service:
//   - before_agent_start retrieves and injects relevant memories.
//   - the remember tool persists durable facts stated by the user.
//
// Run from any directory with: pi -e /path/to/adapters/pi/extension.ts
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const PY = process.env.AGENT_MEMORY_PYTHON ?? process.env.PYTHON ?? "python3";
// Resolve the repository root from adapters/pi so Pi can be launched anywhere.
const REPO_ROOT = fileURLToPath(new URL("../..", import.meta.url));

type MemoryResult = { ok: boolean; output: string };

function callMemory(args: string[]): MemoryResult {
  const r = spawnSync(PY, ["-m", "agent_memory_engine.cli", ...args], {
    encoding: "utf8",
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONPATH: REPO_ROOT },
  });
  if (r.status !== 0) {
    return {
      ok: false,
      output: (r.stderr ?? "").trim() || "The memory subprocess failed.",
    };
  }
  return { ok: true, output: (r.stdout ?? "").trim() };
}

export default function (pi: ExtensionAPI) {
  // Memory retrieval is opt-in per request. The input hook removes the marker so
  // it neither reaches the model nor affects retrieval ranking.
  let injectForNextRequest = false;
  pi.on("input", async (event, _ctx) => {
    const text = event.text.trimStart();
    if (!text.startsWith("@memory")) {
      injectForNextRequest = false;
      return { action: "continue" };
    }

    const remainder = text.slice("@memory".length);
    if (remainder && !/^\s/.test(remainder)) {
      // Do not treat words such as "@memoryless" as the opt-in marker.
      injectForNextRequest = false;
      return { action: "continue" };
    }

    const prompt = remainder.trimStart();
    injectForNextRequest = prompt.length > 0;
    return { action: "transform", text: prompt };
  });

  // Retrieve against the marked prompt immediately before the agent starts.
  pi.on("before_agent_start", async (event, _ctx) => {
    const shouldInject = injectForNextRequest;
    injectForNextRequest = false;
    if (!shouldInject) return;

    const query: string = event.prompt ?? "";
    if (!query) return;
    const result = callMemory(["inject", "--query", query, "--budget", "2000"]);
    if (!result.ok || !result.output) return;
    return {
      message: {
        customType: "agent-memory",
        content: result.output,
        display: true,
      },
    };
  });

  // Give the agent an explicit way to persist durable user knowledge.
  pi.registerTool({
    name: "remember",
    label: "Remember",
    description:
      "When the user states a durable project convention, preference, or important " +
      "fact that should persist across sessions, call this to remember it.",
    promptGuidelines: [
      "Use remember when the user states a durable project convention, preference, or fact worth keeping across sessions.",
    ],
    parameters: Type.Object({
      summary: Type.String({ description: "The fact to remember, one sentence." }),
      tags: Type.Optional(Type.Array(Type.String())),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      const tags = (params.tags ?? []).join(",");
      const result = callMemory(["capture", "--summary", params.summary, "--tags", tags]);
      return {
        content: [{ type: "text", text: result.output }],
        details: {},
        isError: !result.ok,
      };
    },
  });
}
