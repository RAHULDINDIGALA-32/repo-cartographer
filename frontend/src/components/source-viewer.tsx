"use client";

import { useEffect, useRef } from "react";
import { citationLink } from "@/ui/links";
import type { Citation, DoneEvent, RepoSnapshot } from "@/api/types";

export function SourceViewer({
  citation,
  repo,
  done,
  onClose,
  onPrevious,
  onNext,
}: {
  citation?: Citation;
  repo: RepoSnapshot;
  done?: DoneEvent;
  onClose: () => void;
  onPrevious?: () => void;
  onNext?: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "[") onPrevious?.();
      if (event.key === "]") onNext?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onNext, onPrevious]);
  if (!citation) return null;
  const link = citationLink(citation, repo, done);
  const lines = (citation.snippet ?? "").split("\n");
  return (
    <div
      className="viewer-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside className="viewer" role="dialog" aria-modal="true" aria-labelledby="viewer-title">
        <div className="viewer-head">
          <div>
            <h2 id="viewer-title" className="mono">
              {citation.path}
            </h2>
            <p>
              L{citation.start_line}–{citation.end_line}
              {citation.symbol ? ` · ${citation.symbol}` : ""}
            </p>
          </div>
          <button
            ref={closeRef}
            className="icon-button"
            type="button"
            aria-label="Close source viewer"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        {citation.snippet_truncated && (
          <div className="notice">
            This evidence snippet was truncated. Open the pinned file for the complete source.
          </div>
        )}
        {citation.snippet ? (
          <pre className="viewer-code">
            {lines.map((line, index) => (
              <span className={index === 0 ? "source-highlight" : ""} key={`${index}-${line}`}>
                <b>{citation.start_line + index}</b>
                {line}
                {"\n"}
              </span>
            ))}
          </pre>
        ) : (
          <div className="viewer-empty">No snippet was returned for this source.</div>
        )}
        <div className="viewer-foot">
          <a href={link} target="_blank" rel="noopener noreferrer">
            Open on GitHub ↗
          </a>
          <a
            href={`${repo.url}/blob/${repo.defaultBranch ?? "main"}/${citation.path}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            View latest
          </a>
          <button type="button" onClick={() => void navigator.clipboard.writeText(citation.path)}>
            Copy path
          </button>
          <div className="viewer-nav">
            <button type="button" onClick={onPrevious}>
              Previous
            </button>
            <button type="button" onClick={onNext}>
              Next
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}
