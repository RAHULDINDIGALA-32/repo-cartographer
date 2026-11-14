"use client";

import { useEffect, useState } from "react";
import type { Turn } from "@/hooks/use-ask";

export function CommandPalette({
  history,
  onNew,
  onSettings,
  onExport,
  onClose,
}: {
  history: Turn[];
  onNew: () => void;
  onSettings: () => void;
  onExport: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"history" | "actions">("history");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const normalizedQuery = query.trim().toLowerCase();
  const matchingHistory = history
    .filter((turn) =>
      `${turn.repo.owner}/${turn.repo.name} ${turn.question}`
        .toLowerCase()
        .includes(normalizedQuery),
    )
    .slice(-8)
    .reverse();
  const actions = [
    { label: "New chat", run: onNew },
    { label: "Open settings", run: onSettings },
    { label: "Export conversation", run: onExport },
    {
      label: "Admin console",
      run: () => {
        window.location.href = "/admin";
      },
    },
  ];
  const matchingActions = actions.filter((action) =>
    action.label.toLowerCase().includes(normalizedQuery),
  );
  const hasSearch = normalizedQuery.length > 0;
  const runAction = (run: () => void) => {
    run();
    onClose();
  };
  const historyButton = (turn: Turn, searchResult = false) => (
    <button
      type="button"
      className="palette-history"
      key={`${searchResult ? "search-" : ""}${turn.id}`}
      onClick={() => {
        document
          .querySelector(`[data-turn-id="${turn.id}"]`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
        onClose();
      }}
    >
      <span>{searchResult ? "History" : `${turn.repo.owner}/${turn.repo.name}`}</span>
      {searchResult ? `${turn.repo.owner}/${turn.repo.name}: ${turn.question}` : turn.question}
    </button>
  );

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
          placeholder="Search history or actions..."
          aria-label="Command search"
        />
        {hasSearch ? (
          <section className="palette-search-results" aria-labelledby="palette-search-heading">
            <h2 id="palette-search-heading">Search results</h2>
            {matchingHistory.map((turn) => historyButton(turn, true))}
            {matchingActions.map((action) => (
              <button type="button" key={action.label} onClick={() => runAction(action.run)}>
                <span>Action</span>
                {action.label}
              </button>
            ))}
            {!matchingHistory.length && !matchingActions.length && (
              <p className="palette-empty">No matching results.</p>
            )}
          </section>
        ) : (
          <>
            <div className="palette-tabs" role="tablist" aria-label="Command palette sections">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "history"}
                className={activeTab === "history" ? "active" : ""}
                onClick={() => setActiveTab("history")}
              >
                History
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "actions"}
                className={activeTab === "actions" ? "active" : ""}
                onClick={() => setActiveTab("actions")}
              >
                Actions
              </button>
            </div>
            {activeTab === "history" ? (
              <section className="palette-section" aria-labelledby="palette-history-heading">
                <h2 id="palette-history-heading" className="sr-only">
                  History
                </h2>
                {matchingHistory.length ? (
                  matchingHistory.map((turn) => historyButton(turn))
                ) : (
                  <p className="palette-empty">No history yet.</p>
                )}
              </section>
            ) : (
              <section className="palette-section" aria-labelledby="palette-actions-heading">
                <h2 id="palette-actions-heading" className="sr-only">
                  Actions
                </h2>
                {actions.map((action) => (
                  <button type="button" key={action.label} onClick={() => runAction(action.run)}>
                    {action.label}
                  </button>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
