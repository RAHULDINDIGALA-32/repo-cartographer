import { describe, expect, it } from "vitest";
import { isGitHubRepoInput, savingsSummary } from "../src/admin/format";
import { normalizeTrace, traceObservations } from "../src/admin/trace";

describe("F3 admin helpers", () => {
  it("validates GitHub repository inputs without accepting file URLs", () => {
    expect(isGitHubRepoInput("pallets/flask")).toBe(true);
    expect(isGitHubRepoInput("https://github.com/pallets/flask")).toBe(true);
    expect(isGitHubRepoInput("https://github.com/pallets/flask/blob/main/app.py")).toBe(false);
    expect(isGitHubRepoInput("https://example.com/a/b")).toBe(false);
  });
  it("calculates reuse and no-op summaries honestly", () => {
    expect(savingsSummary(97, 3, 4200)).toMatchObject({
      total: 100,
      reuseRatio: 0.97,
      tokensSaved: 4200,
      noOp: false,
    });
    expect(savingsSummary(0, 0, 0).noOp).toBe(true);
  });
  it("normalizes old or incomplete traces and derives only facts", () => {
    const trace = normalizeTrace(
      { fused: [{ id: 2, score: 1 }], reranked: [{ id: 3, score: 2 }], degraded: ["reranker"] },
      { "2": { id: 2, path: "app.py", start_line: 1, end_line: 4 } },
    );
    expect(trace.chunks["2"].path).toBe("app.py");
    expect(traceObservations(trace)).toContain("The reranker changed the top result.");
    expect(traceObservations(trace)).toContain("Degraded components: reranker.");
  });
});
