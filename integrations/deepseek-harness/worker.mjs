import { createInterface } from "node:readline";
import process from "node:process";
import { URL } from "node:url";
import { randomUUID } from "node:crypto";
import { Context } from "@deepseek-ai/cordis";
import Agents from "@deepseek-ai/dsh-agent";
import AgentLoop from "@deepseek-ai/dsh-agent-loop";
import Llm, {
  createAssistantMessage,
  createSystemMessage,
  createUserMessage,
} from "@deepseek-ai/dsh-llm";
import * as PiAi from "@deepseek-ai/dsh-llm-pi-ai";
import Sessions from "@deepseek-ai/dsh-session";
import Projections from "@deepseek-ai/dsh-session-projection";
import SystemPrompt from "@deepseek-ai/dsh-system-prompt";
import Tools from "@deepseek-ai/dsh-tools";

// Private, newline-delimited RPC over the owning Zotero process's pipes.
// The worker loads the agent kernel and proxies the registered Zotero tools.
const input = createInterface({ input: process.stdin });
const pending = new Map();
let context;
let agent;
let initialized = false;
let running = false;
let cancelled = false;
let nextId = 0;
let apiKey = "";

const send = (message) =>
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", ...message }) + "\n");
const event = (value) => send({ method: "event", params: value });
const safeError = (error) => {
  const message = error instanceof Error ? error.message : String(error);
  return apiKey ? message.split(apiKey).join("[redacted]") : message;
};

function callHost(name, args, signal) {
  if (signal.aborted) return Promise.reject(new Error("Cancelled"));
  const id = `tool-${++nextId}`;
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      pending.delete(id);
      reject(new Error("Cancelled"));
    };
    pending.set(id, {
      resolve: (result) => {
        signal.removeEventListener("abort", onAbort);
        resolve(result);
      },
      reject,
    });
    signal.addEventListener("abort", onAbort, { once: true });
    send({ id, method: "tool_call", params: { name, args, callId: id } });
  });
}

async function initialize(config) {
  if (initialized || context) throw new Error("Already initialized");
  if (
    !config ||
    typeof config.model !== "string" ||
    !config.model.trim() ||
    typeof config.apiKey !== "string" ||
    !config.apiKey ||
    !Array.isArray(config.tools)
  )
    throw new Error("Invalid Harness configuration");
  const url = new URL(config.apiBase);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    throw new Error("Expected an HTTP(S) provider endpoint");
  apiKey = config.apiKey;
  process.env.LFZ_HARNESS_API_KEY = apiKey;
  context = new Context();
  await context.plugin(Llm);
  await context.plugin(Sessions);
  await context.plugin(Projections);
  await context.plugin(SystemPrompt, {
    includeHarnessIdentity: false,
    includeRuntimeContext: false,
    personaPrefix: config.systemPrompt || "",
  });
  await context.plugin(Tools, { mode: "native" });
  await context.plugin(Agents);
  await context.plugin(PiAi, {
    providers: {
      "zotero-provider": {
        api: "openai-completions",
        apiKeyEnv: "LFZ_HARNESS_API_KEY",
        baseURL: url.href.replace(/\/$/, ""),
        models: [
          {
            id: config.model,
            contextWindow: config.contextWindow || 131072,
            maxTokens: config.maxTokens || 8192,
          },
        ],
        compat: { supportsStore: false },
        retryPolicy: { mode: "normal", maxRetries: 0 },
      },
    },
  });
  for (const tool of config.tools) {
    context.tools.register({
      name: tool.name,
      description: tool.description,
      parameters: tool.inputSchema,
      output: {
        schema: { type: "string" },
        render: (_args, value) => [{ type: "text", text: value }],
      },
      async execute(args, execution) {
        const result = await callHost(tool.name, args, execution.signal);
        if (!result.ok) throw new Error(JSON.stringify(result));
        return JSON.stringify(result);
      },
    });
  }
  await context.plugin(AgentLoop, { agents: [], maxParallelToolCalls: 1 });
  if (Number.isFinite(config.temperature)) {
    context.on("agent/request", async (_payload, next) => ({
      ...(await next()),
      temperature: config.temperature,
    }));
  }
  const handle = await context.agents.create({
    sessionId: `zotero-${randomUUID()}`,
    agentOptions: {
      provider: "zotero-provider",
      model: config.model,
      maxTokens: config.maxTokens || 8192,
    },
  });
  agent = handle.agent;
  agent.session.append(
    "system/message",
    {
      turn: 0,
      step: 0,
      message: createSystemMessage(config.systemPrompt || ""),
    },
    { surfaceOp: "append" },
  );
  for (const message of config.history || []) {
    if (
      !message ||
      !["user", "assistant"].includes(message.role) ||
      typeof message.content !== "string"
    )
      throw new Error("Invalid text history");
    const content = [{ type: "text", text: message.content }];
    if (message.role === "user") {
      agent.session.append(
        "user/message",
        createUserMessage({ content, source: { kind: "user" } }),
        { surfaceOp: "append" },
      );
    } else {
      agent.session.append(
        "assistant/message",
        {
          turn: 0,
          step: 0,
          message: createAssistantMessage({
            content,
            source: { provider: "zotero-provider", model: config.model },
          }),
          stream: [],
        },
        { surfaceOp: "append" },
      );
    }
  }
  initialized = true;
  return { version: "0.2.0-rc.2", sessionId: agent.id };
}

async function run(text) {
  if (!initialized || running || typeof text !== "string")
    throw new Error("Invalid run request");
  running = true;
  let finalText = "";
  let failure;
  let stopReason;
  const disposers = [];
  try {
    disposers.push(
      context.on("agent/assistant-stream", ({ frame }) => {
        if (frame.type !== "chunk") return;
        const chunk = frame.chunk;
        if (chunk.type === "text-delta")
          event({ type: "message_delta", text: chunk.text });
        if (chunk.type === "reasoning-delta")
          event({
            type: "reasoning",
            round: frame.revision,
            details: chunk.text,
          });
        if (chunk.type === "usage")
          event({
            type: "usage",
            round: frame.revision,
            promptTokens:
              chunk.usage.inputTokens +
              (chunk.usage.cacheReadTokens || 0) +
              (chunk.usage.cacheWriteTokens || 0),
            completionTokens: chunk.usage.outputTokens,
            totalTokens:
              chunk.usage.totalTokens ??
              chunk.usage.inputTokens +
                (chunk.usage.cacheReadTokens || 0) +
                (chunk.usage.cacheWriteTokens || 0) +
                chunk.usage.outputTokens,
            cacheReadTokens: chunk.usage.cacheReadTokens,
            cacheWriteTokens: chunk.usage.cacheWriteTokens,
          });
      }),
    );
    disposers.push(
      context.on("agent/error", ({ error }) => {
        failure = error;
      }),
    );
    disposers.push(
      context.on("session/event", (_session, entry) => {
        if (entry.type === "assistant/message") {
          finalText = entry.data.message.content
            .filter((block) => block.type === "text")
            .map((block) => block.text)
            .join("");
        }
        if (entry.type === "turn/end") stopReason = entry.data.reason;
      }),
    );
    await new Promise((resolve) => {
      const dispose = context.on("agent/status", ({ status }) => {
        if (status === "idle") {
          dispose();
          resolve();
        }
      });
      agent.followup(
        createUserMessage({
          content: [{ type: "text", text }],
          source: { kind: "user" },
        }),
      );
    });
    if (cancelled) throw new Error("Cancelled");
    if (failure) throw failure;
    if (stopReason && stopReason.kind !== "completed")
      throw new Error(`Harness turn ended: ${JSON.stringify(stopReason)}`);
    if (!finalText.trim()) throw new Error("Harness returned no answer");
    return { text: finalText };
  } finally {
    for (const dispose of disposers) dispose();
  }
}

input.on("line", (line) => {
  void (async () => {
    let message;
    try {
      message = JSON.parse(line);
      if (pending.has(message.id)) {
        const entry = pending.get(message.id);
        pending.delete(message.id);
        message.error
          ? entry.reject(new Error(message.error.message))
          : entry.resolve(message.result);
        return;
      }
      let result;
      if (message.method === "initialize")
        result = await initialize(message.params);
      else if (message.method === "run")
        result = await run(message.params?.text);
      else if (message.method === "cancel") {
        cancelled = true;
        agent?.cancel({ kind: "user" });
        return;
      } else throw new Error("Unknown Harness method");
      send({ id: message.id, result });
    } catch (error) {
      send({
        id: message?.id ?? null,
        error: { code: -32603, message: safeError(error) },
      });
    }
  })();
});
input.on("close", () => {
  cancelled = true;
  agent?.cancel({ kind: "user" });
  for (const entry of pending.values())
    entry.reject(new Error("Host disconnected"));
  pending.clear();
  void context?.fiber.dispose().finally(() => process.exit(0));
});
