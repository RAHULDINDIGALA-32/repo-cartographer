"use client";

import { Github } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { BRAND_NAME } from "@/api/config";
import type { Repository } from "@/api/types";
import { useAsk } from "@/hooks/use-ask";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { useRepos } from "@/hooks/use-repos";
import { Composer } from "./composer";
import { RepoSelector } from "./repo-selector";
import { StatusIndicator } from "./status-indicator";
import { ThemeToggle } from "./theme-toggle";
import { Turn } from "./turn";

function selectStored(repos: Repository[]) {
  if (typeof window === "undefined") return repos.find((repo) => repo.status === "ready");
  const stored = Number(localStorage.getItem("repo-cartographer.repo"));
  return repos.find((repo) => repo.id === stored) ?? repos.find((repo) => repo.status === "ready");
}

export function AppShell({ requestedRepoId }: { requestedRepoId?: number }) {
  const backend = useBackendStatus();
  const reposQuery = useRepos(backend.state === "ready" || backend.state === "degraded");
  const [repo, setRepo] = useState<Repository>();
  useEffect(() => {
    if (reposQuery.data?.length) {
      const selected = requestedRepoId
        ? reposQuery.data.find((item) => item.id === requestedRepoId)
        : selectStored(reposQuery.data);
      if (selected) setRepo(selected);
    }
  }, [reposQuery.data, requestedRepoId]);
  useEffect(() => {
    if (repo && typeof window !== "undefined") {
      localStorage.setItem("repo-cartographer.repo", String(repo.id));
      window.history.replaceState({}, "", `/r/${repo.id}`);
    }
  }, [repo]);
  const ask = useAsk(repo?.id);
  const [example, setExample] = useState("");
  const examples = useMemo(() => repo?.examples ?? [], [repo]);
  const send = (question: string) => {
    setExample("");
    void ask.ask(question);
  };
  return (
    <div className="app-shell">
      <a href="#main-content" className="sr-only focus:not-sr-only">
        Skip to content
      </a>
      <header className="header">
        <div className="header-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden>
              ◈
            </span>
            <span className="brand-name">{BRAND_NAME}</span>
          </div>
          <RepoSelector repos={reposQuery.data ?? []} selected={repo} onSelect={setRepo} />
          <StatusIndicator state={backend.state} elapsed={backend.elapsed} />
          <ThemeToggle />
        </div>
      </header>
      <main className="main" id="main-content">
        {backend.state === "waking" && (
          <div className="wake-card" role="status">
            <strong>Waking up the server</strong>
            <br />
            This free-tier host may sleep when idle. The first request can take up to a minute.
            <div className="shimmer" />
            {backend.elapsed > 0 && <small>{backend.elapsed}s elapsed</small>}
          </div>
        )}
        {backend.state === "down" && (
          <div className="notice" role="alert">
            <strong>The backend is unavailable.</strong>
            <br />
            {backend.error ?? "Please try again."}{" "}
            <button type="button" onClick={backend.retry}>
              Retry
            </button>
          </div>
        )}
        {backend.state === "ready" && reposQuery.isLoading && (
          <div className="empty-state">
            <h1>Loading repositories…</h1>
          </div>
        )}
        {backend.state === "ready" && reposQuery.isError && (
          <div className="notice" role="alert">
            Could not load repositories.{" "}
            <button type="button" onClick={() => void reposQuery.refetch()}>
              Retry
            </button>
          </div>
        )}
        {repo && (
          <div className="empty-state">
            <h1>Ask anything about this codebase</h1>
            <p>
              <span className="mono">{repo.url.replace(/^https?:\/\/github\.com\//, "")}</span> ·
              indexed <span className="mono">{repo.indexed_sha?.slice(0, 7) ?? "unknown"}</span>
            </p>
            {!ask.turns.length && examples.length > 0 && (
              <div className="chips" aria-label="Example questions">
                {examples.map((question) => (
                  <button
                    className="chip"
                    type="button"
                    key={question}
                    onClick={() => {
                      setExample(question);
                      send(question);
                    }}
                  >
                    {question}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {!repo && backend.state === "ready" && !reposQuery.isLoading && (
          <div className="empty-state">
            <h1>No ready repositories</h1>
            <p>An administrator must index a public repository before you can ask questions.</p>
          </div>
        )}
        {ask.turns.map((turn) => (
          <Turn key={turn.id} turn={turn} onRetry={() => send(turn.question)} />
        ))}
        <div aria-live="polite" className="sr-only">
          {ask.turns.at(-1)?.state === "complete"
            ? "Answer ready"
            : ask.turns.at(-1)?.state === "error"
              ? "Answer error"
              : ""}
        </div>
      </main>
      <div className="composer-dock">
        <Composer
          disabled={backend.state !== "ready" || !repo}
          active={ask.active}
          onAsk={send}
          onStop={ask.stop}
          initialValue={example}
        />
      </div>
      <footer className="footer">
        <span>
          Public GitHub repositories, grounded answers.</span>
      </footer>
    </div>
  );
}
