import assert from "node:assert/strict";
import test from "node:test";
import { AgroAI, ConflictError, InsufficientBalanceError, NotFoundError, buildRunBody } from "../dist/index.js";

const json = (status, payload, headers = {}) =>
  new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json", ...headers } });

const client = (handler) => new AgroAI({ apiKey: "agro_live_test", baseUrl: "https://api.test", fetch: handler, maxRetries: 2 });

test("run sends the platform contract with an idempotency key", async () => {
  let seen;
  const result = await client(async (url, init) => {
    seen = { url, init, body: JSON.parse(init.body) };
    return json(200, { id: "run_1", status: "completed", structured_output: { tasks: [] } });
  }).intelligence.run({
    question: "What should the crew do today?",
    task: "decision",
    context: { crop: { name: "almond" } },
    responseFormat: "task_list",
    knowledge: ["sops"],
    attachments: ["file_1"],
  });
  assert.equal(result.id, "run_1");
  assert.equal(seen.url, "https://api.test/v1/intelligence");
  assert.deepEqual(seen.body.response_format, { type: "agroai_schema", name: "task_list" });
  assert.deepEqual(seen.body.knowledge, { collections: ["sops"] });
  assert.deepEqual(seen.body.attachments, [{ file_id: "file_1" }]);
  assert.match(seen.init.headers["Idempotency-Key"], /^sdk-/);
  assert.equal("session_id" in seen.body, false);
});

test("retries reuse one idempotency key and typed errors surface", async () => {
  const keys = [];
  const result = await client(async (_url, init) => {
    keys.push(init.headers["Idempotency-Key"]);
    return keys.length < 3 ? json(503, { detail: { code: "intelligence_temporarily_unavailable" } }, { "Retry-After": "0" }) : json(200, { id: "ok" });
  }).intelligence.run({ question: "retry?" });
  assert.equal(result.id, "ok");
  assert.equal(new Set(keys).size, 1);

  await assert.rejects(
    client(async () => json(402, { detail: { code: "insufficient_intelligence_balance", required_cents: 50 } })).intelligence.run({ question: "pay?" }),
    (error) => error instanceof InsufficientBalanceError && error.body.required_cents === 50,
  );
  let calls = 0;
  await assert.rejects(
    client(async () => { calls += 1; return json(409, { detail: { code: "idempotency_key_reused_with_different_request" } }); }).intelligence.run({ question: "dup?" }),
    ConflictError,
  );
  assert.equal(calls, 1, "a changed-request conflict is never retried");
  await assert.rejects(client(async () => json(404, { detail: { code: "intelligence_job_not_found" } })).intelligence.jobs.retrieve("x"), NotFoundError);
});

test("stream yields server-sent events incrementally", async () => {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('event: run.created\ndata: {"id":"r"}\n\n: keep-alive\n\n'));
      controller.enqueue(encoder.encode('event: run.completed\ndata: {"id":"r","status":"completed"}\n\n'));
      controller.close();
    },
  });
  const events = [];
  for await (const event of client(async () => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } })).intelligence.stream({ question: "s?" })) {
    events.push(event);
  }
  assert.deepEqual(events.map((e) => e.event), ["run.created", "run.completed"]);
  assert.equal(events[1].data.status, "completed");
});

test("jobs.wait polls to a terminal state", async () => {
  const states = ["queued", "running", "completed"];
  const c = client(async (_url, init) => (init.method === "POST" ? json(202, { id: "job_1", status: "queued" }) : json(200, { id: "job_1", status: states.shift() })));
  const job = await c.intelligence.jobs.create({ question: "season report", task: "report" });
  const done = await c.intelligence.jobs.wait(job.id, { pollIntervalMs: 1 });
  assert.equal(done.status, "completed");
});

test("custom JSON schema passes through", () => {
  const body = buildRunBody({ question: "x?", responseFormat: { type: "json_schema", schema: { type: "object" } } });
  assert.deepEqual(body.response_format, { type: "json_schema", schema: { type: "object" } });
});

test("files.upload sends the requested content type even for an existing untyped Blob", async () => {
  let form;
  await client(async (_url, init) => { form = init.body; return json(201, { id: "file_1" }); })
    .intelligence.files.upload(new Blob(["scouted rows"]), { filename: "notes.txt", contentType: "text/plain" });
  const part = form.get("file");
  assert.equal(part.type, "text/plain");
  assert.equal(part.name, "notes.txt");
  assert.equal(await part.text(), "scouted rows");
});
