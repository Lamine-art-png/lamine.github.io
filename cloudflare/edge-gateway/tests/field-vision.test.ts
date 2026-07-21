import { describe, expect, it, vi } from "vitest";
import { handleFieldVision } from "../src/edge-main-v3";

const URL = "https://api.agroai-pilot.com/v1/internal/edge/field-vision";

function env(run = vi.fn(async () => ({ description: '{"summary":"Dry leaf edge","observations":["brown edge"],"possible_issue":"possible stress","severity":"medium","confidence":0.6,"recommended_follow_up":"inspect plants","uncertainties":["photo only"]}' }))) {
  return {
    QUEUE_CONSUMER_TOKEN: "consumer-secret",
    QUEUE_PUBLISH_TOKEN: "publish-secret",
    CONNECTOR_TASKS: {} as Queue,
    UPSTREAM_API_ORIGIN: "https://api-preview.agroai-pilot.com",
    AI: { run },
  } as any;
}

function request(payload: Record<string, unknown>, token = "consumer-secret") {
  return new Request(URL, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

describe("Field Intelligence Workers AI vision bridge", () => {
  it("authenticates the backend and invokes only the approved visual model", async () => {
    const run = vi.fn(async () => ({ description: "field evidence" }));
    const response = await handleFieldVision(request({
      image: "AQIDBA==",
      content_type: "image/jpeg",
      model: "@cf/llava-hf/llava-1.5-7b-hf",
      prompt: "Describe visible field evidence",
    }), env(run));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ success: true, result: { description: "field evidence" } });
    expect(run).toHaveBeenCalledWith("@cf/llava-hf/llava-1.5-7b-hf", {
      image: [1, 2, 3, 4],
      prompt: "Describe visible field evidence",
      max_tokens: 900,
    });
  });

  it("rejects unauthorized, malformed, and unapproved requests", async () => {
    const run = vi.fn();
    expect((await handleFieldVision(request({ image: "AQIDBA==" }, "wrong"), env(run))).status).toBe(401);
    expect((await handleFieldVision(request({
      image: "not base64",
      content_type: "image/jpeg",
      prompt: "inspect",
    }), env(run))).status).toBe(400);
    expect((await handleFieldVision(request({
      image: "AQIDBA==",
      content_type: "application/pdf",
      prompt: "inspect",
    }), env(run))).status).toBe(400);
    expect((await handleFieldVision(request({
      image: "AQIDBA==",
      content_type: "image/png",
      model: "@cf/unapproved/model",
      prompt: "inspect",
    }), env(run))).status).toBe(400);
    expect(run).not.toHaveBeenCalled();
  });

  it("returns a generic failure without leaking provider details", async () => {
    const run = vi.fn(async () => { throw new Error("sensitive provider output"); });
    const response = await handleFieldVision(request({
      image: "AQIDBA==",
      content_type: "image/webp",
      prompt: "inspect",
    }), env(run));
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ success: false, error: "workers_ai_unavailable" });
  });
});
