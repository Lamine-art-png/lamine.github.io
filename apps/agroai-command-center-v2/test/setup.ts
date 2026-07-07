import { vi } from "vitest";

vi.stubGlobal(
  "fetch",
  vi.fn(async () => {
    throw new Error("External network is disabled in command-center unit tests");
  }),
);
