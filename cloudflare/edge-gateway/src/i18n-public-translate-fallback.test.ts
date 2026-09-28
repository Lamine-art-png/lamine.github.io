import { afterEach, describe, expect, it, vi } from "vitest";

import { translateWithPublicFallback } from "./i18n-public-translate-fallback";

function googlePayload(value: string) {
  return [[ [value, "source", null, null] ], null, "en"];
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("public translation provider recovery", () => {
  it("reconstructs the catalog by original keys when Google strips batch item markers", async () => {
    const individual: Record<string, string> = {
      Language: "ቋንቋ",
      Settings: "ቅንብሮች",
      Save: "አስቀምጥ",
      Support: "ድጋፍ",
    };
    const requests: string[] = [];

    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const url = new URL(raw);
      const query = url.searchParams.get("q") || "";
      requests.push(query);

      // This matches the live Amharic failure: Google returns translated copy
      // but removes/translates the AGROAI_ITEM markers used for batch decoding.
      if (query.includes("AGROAI_ITEM_")) {
        return new Response(JSON.stringify(googlePayload("ቋንቋ\nቅንብሮች\nአስቀምጥ\nድጋፍ")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }

      const translated = individual[query];
      if (!translated) return new Response("not found", { status: 500 });
      return new Response(JSON.stringify(googlePayload(translated)), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }));

    const source = {
      language: "Language",
      settings: "Settings",
      save: "Save",
      support: "Support",
    };

    const catalog = await translateWithPublicFallback("am", source);

    expect(catalog).toEqual({
      language: "ቋንቋ",
      settings: "ቅንብሮች",
      save: "አስቀምጥ",
      support: "ድጋፍ",
    });
    expect(requests[0]).toContain("AGROAI_ITEM_");
    expect(requests).toEqual(expect.arrayContaining(["Language", "Settings", "Save", "Support"]));
  });

  it("still rejects individual recovery that breaks placeholders", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const url = new URL(raw);
      const query = url.searchParams.get("q") || "";

      if (query.includes("AGROAI_ITEM_")) {
        return new Response(JSON.stringify(googlePayload("markerless translated text")), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }

      // Drop {recipient}; final validCatalog must reject this provider result.
      const translated = query.includes("recipient") ? "Imetumwa" : `SW ${query}`;
      return new Response(JSON.stringify(googlePayload(translated)), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }));

    await expect(translateWithPublicFallback("sw", {
      delivered: "Sent to {recipient}",
      save: "Save",
    })).rejects.toThrow(/public_translation_provider_chain_exhausted/);
  });
});
