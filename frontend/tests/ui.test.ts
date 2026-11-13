import { describe, expect, it } from "vitest";
import { protectMarkdownCode, knownCitationIndexes } from "../src/ui/markers";
import { userFacingError } from "../src/ui/errors";

describe("frontend safety utilities", () => {
  it("does not transform citation markers inside code", () => {
    const result = protectMarkdownCode("See [1]. `ignore [1]` ```\n[1]\n```", (value) =>
      knownCitationIndexes(value, new Set([1])),
    );
    expect(result).toBe("See ⟦1⟧. `ignore [1]` ```\n[1]\n```");
  });
  it("maps backend errors without exposing raw details", () => {
    expect(userFacingError(new Error("secret stack"))).toEqual({
      title: "Connection lost",
      retryable: true,
    });
  });
});
