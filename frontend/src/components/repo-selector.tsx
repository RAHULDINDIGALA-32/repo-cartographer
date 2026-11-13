"use client";

import { ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";
import type { Repository } from "@/api/types";

function repoName(url: string) {
  return url.replace(/^https?:\/\/github\.com\//, "").replace(/\/$/, "");
}
function age(value: string | null) {
  if (!value) return "not indexed";
  const seconds = Math.max(0, (Date.now() - Date.parse(value)) / 1000);
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function RepoSelector({
  repos,
  selected,
  onSelect,
}: {
  repos: Repository[];
  selected?: Repository;
  onSelect: (repo: Repository) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => repos.filter((repo) => repoName(repo.url).toLowerCase().includes(query.toLowerCase())),
    [repos, query],
  );
  return (
    <div className="repo-selector">
      <div className="repo-menu-wrap">
        <button
          className="repo-select"
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <span>{selected ? repoName(selected.url) : "Choose a repository"}</span>
          <ChevronDown size={15} aria-hidden />
        </button>
        {open && (
          <div className="repo-menu" role="dialog" aria-label="Choose repository">
            <input
              className="repo-search"
              aria-label="Search repositories"
              placeholder="Search repositories"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              autoFocus
            />
            {filtered.length ? (
              filtered.map((repo) => {
                const ready = repo.status === "ready";
                return (
                  <button
                    className="repo-option"
                    type="button"
                    key={repo.id}
                    aria-disabled={!ready}
                    onClick={() => {
                      if (ready) {
                        onSelect(repo);
                        setOpen(false);
                      }
                    }}
                    title={ready ? undefined : "This repository is not ready yet"}
                  >
                    <span>
                      <strong>{repoName(repo.url)}</strong>
                      <br />
                      <small className="mono">
                        {repo.indexed_sha?.slice(0, 7) ?? "—"} · {age(repo.indexed_at)}
                      </small>
                    </span>
                    <small>{repo.status}</small>
                  </button>
                );
              })
            ) : (
              <p className="text-muted">No repositories found.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
