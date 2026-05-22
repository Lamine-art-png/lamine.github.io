import { describe, expect, it } from "vitest";
import { buildPrecomputedSampleResponse } from "../src/adapters/demo/sampleResponse";

describe("sample response snapshot", () => {
  it("is stable byte-for-byte", async () => {
    const first = JSON.stringify(await buildPrecomputedSampleResponse());
    const second = JSON.stringify(await buildPrecomputedSampleResponse());
    expect(first).toBe(second);
    expect(first).toMatchSnapshot();
  });
});

