"use client";

import type { Citation, RetrievalEvent } from "@/api/types";

export function RetrievalInspector({
  retrieval,
  citations,
  onOpen,
}: {
  retrieval?: RetrievalEvent;
  citations: Citation[];
  onOpen: (index: number) => void;
}) {
  const rows = retrieval?.ranked ?? retrieval?.hits ?? [];
  const cited = new Set(citations.map((item) => item.chunk_id));
  const max = Math.max(...rows.map((item) => Number(item.score ?? 0)), 0.001);
  if (!retrieval) return null;
  return (
    <details className="inspector">
      <summary>
        Context · {retrieval.count ?? rows.length} retrieved / {retrieval.kept ?? "—"} kept /{" "}
        {citations.length} cited
      </summary>
      <p className="inspector-honesty">
        Retrieved context is what the model could see; only cited sources are claimed as evidence.
      </p>
      {rows.slice(0, 20).map((row, index) => {
        const id = Number(row.chunk_id ?? row.id);
        const score = Number(row.score ?? 0);
        return (
          <button
            className="inspector-row"
            type="button"
            key={`${id}-${index}`}
            onClick={() => onOpen(id)}
          >
            <span>{index + 1}</span>
            <span className="source-path mono">
              {String(row.path ?? "unknown")}:L{String(row.start_line ?? "?")}–
              {String(row.end_line ?? "?")}
            </span>
            <span className="score-bar">
              <i style={{ width: `${Math.max(4, (score / max) * 100)}%` }} />
            </span>
            {cited.has(id) && <small>cited</small>}
          </button>
        );
      })}
    </details>
  );
}
