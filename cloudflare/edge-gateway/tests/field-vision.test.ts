import { describe, expect, it, vi } from "vitest";
import { handleFieldVision } from "../src/edge-main-v3";

const URL = "https://api.agroai-pilot.com/v1/internal/edge/field-vision";
const PRIMARY_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct";
const FALLBACK_MODEL = "@cf/llava-hf/llava-1.5-7b-hf";

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
  it("uses the stronger approved primary model with the documented data URI input", async () => {
    const run = vi.fn(async () => ({ response: "field evidence" }));
    const response = await handleFieldVision(request({
      image: "AQIDBA==",
      content_type: "image/jpeg",
      prompt: "Describe visible field evidence",
    }), env(run));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      success: true,
      result: { response: "field evidence" },
      model: PRIMARY_MODEL,
      degraded: false,
    });
    expect(run).toHaveBeenCalledWith(PRIMARY_MODEL, {
      image: "data:image/jpeg;base64,AQIDBA==",
      prompt: "Describe visible field evidence",
      max_tokens: 1400,
      temperature: 0.1,
    });
  });

  it("supports the bounded approved fallback and reports degraded provenance", async () => {
    const run = vi.fn(async () => ({ description: "field evidence" }));
    const response = await handleFieldVision(request({
      image: "AQIDBA==",
      content_type: "image/jpeg",
      model: FALLBACK_MODEL,
      prompt: "Describe visible field evidence",
    }), env(run));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      success: true,
      result: { description: "field evidence" },
      model: FALLBACK_MODEL,
      degraded: true,
    });
    expect(run).toHaveBeenCalledWith(FALLBACK_MODEL, {
      image: [1, 2, 3, 4],
      prompt: "Describe visible field evidence",
      max_tokens: 1400,
    });
  });

  it("falls back only when the stronger primary model is unavailable", async () => {
    const run = vi.fn()
      .mockRejectedValueOnce(new Error("primary unavailable"))
      .mockResolvedValueOnce({ description: "fallback evidence" });
    const response = await handleFieldVision(request({
      image: "AQIDBA==",
      content_type: "image/webp",
      prompt: "inspect",
    }), env(run));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      success: true,
      result: { description: "fallback evidence" },
      model: FALLBACK_MODEL,
      degraded: true,
    });
    expect(run).toHaveBeenNthCalledWith(1, PRIMARY_MODEL, {
      image: "data:image/webp;base64,AQIDBA==",
      prompt: "inspect",
      max_tokens: 1400,
      temperature: 0.1,
    });
    expect(run).toHaveBeenNthCalledWith(2, FALLBACK_MODEL, {
      image: [1, 2, 3, 4],
      prompt: "inspect",
      max_tokens: 1400,
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
