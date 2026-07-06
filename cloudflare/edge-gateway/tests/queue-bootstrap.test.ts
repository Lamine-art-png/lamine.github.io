import { describe, expect, it, vi } from "vitest";
import { consumeTask, type ConnectorTaskEnvelope, type Env } from "../src/index";

describe("queue bootstrap safety", () => {
  it("retries and never acknowledges when consumer custody is absent", async () => {
    const ack = vi.fn();
    const retry = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const message = {
      body: { job_id: "job-1", tenant_id: "tenant-1", task_type: "connector_provider_sync" },
      id: "message-1",
      attempts: 0,
      ack,
      retry,
    } as unknown as Message<ConnectorTaskEnvelope>;
    const env = {
      UPSTREAM_API_ORIGIN: "https://api-preview.agroai-pilot.com",
      QUEUE_CONSUMER_TOKEN: "",
      QUEUE_PUBLISH_TOKEN: "publish-test-value",
      CONNECTOR_TASKS: {},
    } as unknown as Env;

    await consumeTask(message, env);

    expect(retry).toHaveBeenCalledTimes(1);
    expect(ack).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
