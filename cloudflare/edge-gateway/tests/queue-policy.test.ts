import { describe, expect, it } from "vitest";
import { matchesConfiguredToken, retryDelaySeconds, shouldAcknowledgeUpstream } from "../src/queue-policy";

describe("Queue acknowledgement policy", () => {
  it("acknowledges only explicit successful upstream responses", () => {
    expect(shouldAcknowledgeUpstream(200)).toBe(true);
    expect(shouldAcknowledgeUpstream(202)).toBe(true);
    expect(shouldAcknowledgeUpstream(204)).toBe(true);
    for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
      expect(shouldAcknowledgeUpstream(status)).toBe(false);
    }
  });

  it("supports bounded exponential retry delays", () => {
    expect(retryDelaySeconds(0)).toBe(15);
    expect(retryDelaySeconds(1)).toBe(30);
    expect(retryDelaySeconds(4)).toBe(240);
    expect(retryDelaySeconds(100)).toBe(900);
  });
});

describe("Queue publish token rotation", () => {
  it("accepts the current or previous configured token only", () => {
    expect(matchesConfiguredToken("new-value", "new-value", "old-value")).toBe(true);
    expect(matchesConfiguredToken("old-value", "new-value", "old-value")).toBe(true);
    expect(matchesConfiguredToken("wrong-value", "new-value", "old-value")).toBe(false);
    expect(matchesConfiguredToken("", "new-value", "old-value")).toBe(false);
  });
});
