import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { once } from "node:events";
import process from "node:process";
import { URL, fileURLToPath } from "node:url";
import { setTimeout, clearTimeout } from "node:timers";

async function fixture(t, respond) {
  const requests = [];
  const server = createServer(async (request, response) => {
    let body = "";
    for await (const chunk of request) body += chunk;
    requests.push(JSON.parse(body));
    respond(response, requests.at(-1), requests.length);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const child = spawn(process.execPath, [
    fileURLToPath(new URL("./worker.mjs", import.meta.url)),
  ]);
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  const pending = new Map();
  const events = [];
  let sequence = 0;
  let onTool = async () => ({ ok: true, content: { count: 7 } });
  const send = (value) =>
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", ...value }) + "\n");
  createInterface({ input: child.stdout }).on("line", (line) => {
    const message = JSON.parse(line);
    if (message.method === "event") events.push(message.params);
    else if (message.method === "tool_call") {
      void onTool(message.params).then((result) =>
        send({ id: message.id, result }),
      );
    } else {
      const entry = pending.get(message.id);
      if (!entry) return;
      pending.delete(message.id);
      if (message.error) entry.reject(new Error(message.error.message));
      else entry.resolve(message.result);
    }
  });
  child.on("exit", () => {
    for (const entry of pending.values())
      entry.reject(new Error(`Worker exited: ${stderr}`));
  });
  t.after(async () => {
    const exit = once(child, "exit");
    child.stdin.end();
    const timer = setTimeout(() => child.kill("SIGKILL"), 2000);
    await exit;
    clearTimeout(timer);
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  });
  const request = (method, params) =>
    new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject });
      send({ id, method, params });
    });
  const configuration = {
    model: "fixture-model",
    apiBase: `http://127.0.0.1:${server.address().port}/v1`,
    apiKey: "fixture-secret",
    systemPrompt: "Answer using the tools.",
    tools: [
      {
        name: "library_search",
        description: "Search the library",
        inputSchema: {
          type: "object",
          properties: { query: { type: "string" } },
          required: ["query"],
        },
      },
    ],
  };
  return {
    request,
    send,
    requests,
    events,
    configuration,
    setTool: (handler) => {
      onTool = handler;
    },
  };
}

function stream(response, delta, finish = "stop") {
  response.writeHead(200, { "Content-Type": "text/event-stream" });
  for (const choice of [
    { delta: { role: "assistant", ...delta }, finish_reason: null },
    { delta: {}, finish_reason: finish },
  ])
    response.write(
      `data: ${JSON.stringify({ id: "completion-1", object: "chat.completion.chunk", model: "fixture-model", choices: [{ index: 0, ...choice }] })}\n\n`,
    );
  response.write(
    `data: ${JSON.stringify({ choices: [], usage: { prompt_tokens: 20, completion_tokens: 10, total_tokens: 30 } })}\n\n`,
  );
  response.end("data: [DONE]\n\n");
}

test(
  "real Harness loop calls a host tool, continues, streams, and preserves history roles",
  { timeout: 20000 },
  async (t) => {
    const f = await fixture(t, (response, _request, round) => {
      if (round === 1)
        stream(
          response,
          {
            tool_calls: [
              {
                index: 0,
                id: "call-1",
                type: "function",
                function: {
                  name: "library_search",
                  arguments: '{"query":"test"}',
                },
              },
            ],
          },
          "tool_calls",
        );
      else stream(response, { content: "Found 7 papers." });
    });
    await f.request("initialize", {
      ...f.configuration,
      temperature: 0.2,
      maxTokens: 1024,
      history: [
        { role: "user", content: "Remember fixture-42" },
        { role: "assistant", content: "I remember fixture-42" },
      ],
    });
    const calls = [];
    f.setTool(async (call) => {
      calls.push(call);
      return { ok: true, content: { count: 7 } };
    });
    const result = await f.request("run", { text: "Count the papers." });
    assert.equal(result.text, "Found 7 papers.");
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args, { query: "test" });
    assert.equal(f.requests.length, 2);
    assert.equal(f.requests[0].temperature, 0.2);
    assert.equal(
      f.requests[0].max_tokens ?? f.requests[0].max_completion_tokens,
      1024,
    );
    assert(
      f.requests[0].messages.some(
        (m) => m.role === "assistant" && m.content.includes("fixture-42"),
      ),
    );
    assert(
      f.requests[1].messages.some(
        (m) => m.role === "tool" && m.content.includes('"count":7'),
      ),
    );
    assert.equal(
      f.events
        .filter((e) => e.type === "message_delta")
        .map((e) => e.text)
        .join(""),
      result.text,
    );
    assert(f.events.some((e) => e.type === "usage" && e.promptTokens === 20));
  },
);

test(
  "a denied tool is an error result and the model can answer",
  { timeout: 20000 },
  async (t) => {
    const f = await fixture(t, (response, _request, round) =>
      round === 1
        ? stream(
            response,
            {
              tool_calls: [
                {
                  index: 0,
                  id: "call-2",
                  type: "function",
                  function: {
                    name: "library_search",
                    arguments: '{"query":"test"}',
                  },
                },
              ],
            },
            "tool_calls",
          )
        : stream(response, { content: "Permission denied." }),
    );
    f.setTool(async () => ({
      ok: false,
      content: { error: "Permission denied" },
    }));
    await f.request("initialize", f.configuration);
    const result = await f.request("run", { text: "Use the search tool." });
    assert.equal(result.text, "Permission denied.");
    assert(
      f.requests[1].messages.some(
        (m) => m.role === "tool" && m.content.includes("Permission denied"),
      ),
    );
  },
);

test(
  "cancel interrupts an outstanding provider stream",
  { timeout: 20000 },
  async (t) => {
    let providerStarted;
    const started = new Promise((resolve) => {
      providerStarted = resolve;
    });
    const f = await fixture(t, (response) => {
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      response.write(": ready\n\n");
      providerStarted();
    });
    await f.request("initialize", f.configuration);
    const run = f.request("run", { text: "Wait for cancellation." });
    const rejected = assert.rejects(run, /Cancelled/);
    await started;
    f.send({ method: "cancel" });
    await rejected;
  },
);

test(
  "provider failures reject the run and redact the key",
  { timeout: 20000 },
  async (t) => {
    const f = await fixture(t, (response) => {
      response.writeHead(401, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          error: {
            message: "Invalid fixture-secret",
            type: "authentication_error",
          },
        }),
      );
    });
    await f.request("initialize", f.configuration);
    await assert.rejects(f.request("run", { text: "Hello" }), (error) => {
      assert(!error.message.includes("fixture-secret"));
      return true;
    });
  },
);
