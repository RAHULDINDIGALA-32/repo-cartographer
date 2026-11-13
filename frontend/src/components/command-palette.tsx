"use client";

import { useEffect, useState } from "react";
import type { Repository } from "@/api/types";
import type { Turn } from "@/hooks/use-ask";

export function CommandPalette({
  repos,
  history,
  onSelectRepo,
  onNew,
  onSettings,
  onExport,
  onClose,
}: {
  repos: Repository[];
  history: Turn[];
  onSelectRepo: (repo: Repository) => void;
  onNew: () => void;
  onSettings: () => void;
  onExport: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const filtered = repos.filter((repo) => repo.url.toLowerCase().includes(query.toLowerCase()));
  const matchingHistory = history
    .filter((turn) =>
      `${turn.repo.owner}/${turn.repo.name} ${turn.question}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .slice(-8)
    .reverse();
  return (
    <div
      className="palette-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search repositories or actions…"
          aria-label="Command search"
        />
        <div className="palette-results">
          {filtered.map((repo) => (
            <button
              type="button"
              key={repo.id}
              onClick={() => {
                onSelectRepo(repo);
                onClose();
              }}
            >
              Switch to {repo.url.replace(/^https?:\/\/github\.com\//, "")}
            </button>
          ))}
          {matchingHistory.map((turn) => (
            <button
              type="button"
              className="palette-history"
              key={turn.id}
              onClick={() => {
                document
                  .querySelector(`[data-turn-id="${turn.id}"]`)
                  ?.scrollIntoView({ behavior: "smooth", block: "center" });
                onClose();
              }}
            >
              <span>History</span> {turn.question}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              onNew();
              onClose();
            }}
          >
            New chat
          </button>
          <button
            type="button"
            onClick={() => {
              onSettings();
              onClose();
            }}
          >
            Open settings
          </button>
          <button
            type="button"
            onClick={() => {
              onExport();
              onClose();
            }}
          >
            Export conversation
          </button>
        </div>
      </div>
    </div>
  );
}
