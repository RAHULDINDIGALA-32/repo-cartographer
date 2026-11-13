import { describe, expect, it } from "vitest";
import type { Citation } from "../src/api/types";
import { citationLink, repoSnapshot } from "../src/ui/links";
import { searchHistory, type HistoryRecord } from "../src/history/store";

const repo = repoSnapshot(
  "https://github.com/acme/example",
  7,
  "abc123",
  "2026-01-01T00:00:00Z",
  "trunk",
);

describe("F2 explainability helpers", () => {
  it("builds a pinned and safely encoded source link", () => {
    const citation: Citation = {
      index: 1,
      chunk_id: 42,
      path: "src/a file.ts",
      start_line: 4,
      end_line: 8,
    };
    expect(citationLink(citation, repo)).toBe(
      "https://github.com/acme/example/blob/abc123/src/a%20file.ts#L4-L8",
    );
  });

  it("rejects a citation permalink that points outside the repository", () => {
    const citation: Citation = {
      index: 1,
      chunk_id: 42,
      path: "src/app.ts",
      start_line: 1,
      end_line: 1,
      permalink: "https://example.com/unsafe",
    };
    expect(citationLink(citation, repo)).toBe(
      "https://github.com/acme/example/blob/abc123/src/app.ts#L1",
    );
  });

  it("uses the default branch only when no indexed SHA is available", () => {
    const citation: Citation = {
      index: 1,
      chunk_id: 42,
      path: "src/app.ts",
      start_line: 1,
      end_line: 1,
    };
    expect(citationLink(citation, { ...repo, indexedSha: null })).toBe(
      "https://github.com/acme/example/blob/trunk/src/app.ts#L1",
    );
  });

  it("searches persisted history without changing stored records", () => {
    const records = [
      {
        schemaVersion: 1,
        id: "a",
        repo,
        question: "How are routes registered?",
        answer: "...",
        state: "complete",
        citations: [],
        createdAt: 1,
      } as HistoryRecord,
      {
        schemaVersion: 1,
        id: "b",
        repo,
        question: "Where is the database pool?",
        answer: "...",
        state: "complete",
        citations: [],
        createdAt: 2,
      } as HistoryRecord,
    ];
    expect(searchHistory(records, "ROUTES").map((item) => item.id)).toEqual(["a"]);
    expect(searchHistory(records, "")).toHaveLength(2);
  });
});
