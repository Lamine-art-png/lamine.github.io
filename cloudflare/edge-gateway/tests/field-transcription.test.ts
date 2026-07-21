import { describe, expect, it, vi } from "vitest";
import { handleFieldTranscription } from "../src/edge-main-v3";

const URL = "https://api.agroai-pilot.com/v1/internal/edge/field-transcription";

function env(run = vi.fn(async () => ({ text: "Irrigation completed", language: "en" }))) {
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

describe("Field Intelligence Workers AI bridge", () => {
  it("authenticates the backend and invokes only the approved transcription model", async () => {
    const run = vi.fn(async () => ({ text: "Irrigation completed", language: "en" }));
    const response = await handleFieldTranscription(request({
      audio: "AQIDBA==",
      model: "@cf/openai/whisper-large-v3-turbo",
      language: "en",
    }), env(run));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      success: true,
      result: { text: "Irrigation completed", language: "en" },
    });
    expect(run).toHaveBeenCalledTimes(1);
    expect(run).toHaveBeenCalledWith("@cf/openai/whisper-large-v3-turbo", {
      audio: "AQIDBA==",
      task: "transcribe",
      vad_filter: true,
      condition_on_previous_text: false,
      language: "en",
    });
  });

  it("rejects missing or incorrect backend credentials before invoking AI", async () => {
    const run = vi.fn();
    const response = await handleFieldTranscription(request({ audio: "AQIDBA==" }, "wrong"), env(run));
    expect(response.status).toBe(401);
    expect(run).not.toHaveBeenCalled();
  });

  it("rejects malformed audio, language, and model inputs", async () => {
    const run = vi.fn();
    expect((await handleFieldTranscription(request({ audio: "not base64" }), env(run))).status).toBe(400);
    expect((await handleFieldTranscription(request({
      audio: "AQIDBA==",
      model: "@cf/unapproved/model",
    }), env(run))).status).toBe(400);
    const languageResponse = await handleFieldTranscription(request({
      audio: "AQIDBA==",
      language: "../../secret",
    }), env(run));
    expect(languageResponse.status).toBe(200);
    expect(run).toHaveBeenLastCalledWith("@cf/openai/whisper-large-v3-turbo", expect.not.objectContaining({ language: expect.anything() }));
  });

  it("returns a generic provider failure without leaking provider output", async () => {
    const run = vi.fn(async () => { throw new Error("sensitive upstream detail"); });
    const response = await handleFieldTranscription(request({ audio: "AQIDBA==" }), env(run));
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ success: false, error: "workers_ai_unavailable" });
  });
});
