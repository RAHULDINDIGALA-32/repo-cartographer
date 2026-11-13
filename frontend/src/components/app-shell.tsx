"use client";

import { useEffect, useMemo, useState } from "react";
import { Command } from "lucide-react";
import dynamic from "next/dynamic";
import { BRAND_NAME } from "@/api/config";
import type { Repository } from "@/api/types";
import { useAsk } from "@/hooks/use-ask";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { useRepos } from "@/hooks/use-repos";
import { loadHistory, saveTurn } from "@/history/store";
import {
  defaultSettings,
  loadSettings,
  saveSettings,
  type FrontendSettings,
} from "@/history/settings";
import { repoSnapshot } from "@/ui/links";
import { Composer } from "./composer";
import { RepoSelector } from "./repo-selector";
import { StatusIndicator } from "./status-indicator";
import { ThemeToggle } from "./theme-toggle";
import { Turn } from "./turn";
const CommandPalette = dynamic(
  () => import("./command-palette").then((module) => module.CommandPalette),
  { ssr: false },
);
const SettingsMenu = dynamic(
  () => import("./settings-menu").then((module) => module.SettingsMenu),
  { ssr: false },
);

function selectStored(repos: Repository[]) {
  if (typeof window === "undefined") return repos.find((repo) => repo.status === "ready");
  const stored = Number(localStorage.getItem("repo-cartographer.repo"));
  return repos.find((repo) => repo.id === stored) ?? repos.find((repo) => repo.status === "ready");
}

export function AppShell({
  requestedRepoId,
  initialQuestion,
}: {
  requestedRepoId?: number;
  initialQuestion?: string;
}) {
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
  const [settings, setSettings] = useState<FrontendSettings>(defaultSettings);
  const [palette, setPalette] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [prefill, setPrefill] = useState(initialQuestion ?? "");
  const ask = useAsk(
    repo
      ? repoSnapshot(repo.url, repo.id, repo.indexed_sha, repo.indexed_at, repo.default_branch)
      : undefined,
    settings.showRetrievalDetails,
  );
  const { hydrate } = ask;
  useEffect(() => {
    setSettings(loadSettings());
    void loadHistory().then((history) => hydrate(history));
  }, [hydrate]);
  useEffect(() => {
    if (!settings.saveHistory) return;
    for (const turn of ask.turns)
      if (turn.state === "complete" || turn.state === "stopped") void saveTurn(turn);
  }, [ask.turns, settings.saveHistory]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const examples = useMemo(() => repo?.examples ?? [], [repo]);
  const send = (question: string) => {
    setPrefill("");
    void ask.ask(question);
  };
  const exportConversation = () => {
    const body = ask.turns
      .map(
        (turn) =>
          `## ${turn.repo.owner}/${turn.repo.name}\n\n### ${turn.question}\n\n${turn.answer}\n\n${turn.citations.map((source) => `- ${source.path}:L${source.start_line}–${source.end_line}`).join("\n")}`,
      )
      .join("\n\n");
    const url = URL.createObjectURL(new Blob([body], { type: "text/markdown" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "repo-cartographer-conversation.md";
    anchor.click();
    URL.revokeObjectURL(url);
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
          <SettingsMenu
            forceOpen={settingsOpen}
            onOpenChange={setSettingsOpen}
            onChange={(next) => {
              setSettings(next);
              saveSettings(next);
            }}
            onClear={() => ask.hydrate([])}
          />
          <button
            className="icon-button"
            type="button"
            aria-label="Open command palette"
            onClick={() => setPalette(true)}
          >
            <Command size={16} aria-hidden />
          </button>
          <ThemeToggle />
        </div>
      </header>
      <main className="main" id="main-content">
        {backend.state === "waking" && (
          <div className="wake-card" role="status">
            <strong>Waking up the server</strong>
            <br />
            This host may sleep when idle. The first request can take up to a minute.
            <div className="shimmer" />
            {backend.elapsed > 0 && <small>{backend.elapsed}s elapsed</small>}
          </div>
        )}
        {backend.state === "down" && (
          <div className="notice" role="alert">
            <strong>The server is unavailable.</strong>
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
                      setPrefill(question);
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
          <Turn
            key={turn.id}
            turn={turn}
            onRetry={() => send(turn.question)}
            onPersist={(saved) => {
              if (settings.saveHistory) void saveTurn(saved);
            }}
          />
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
          key={prefill}
          initialValue={prefill}
          disabled={backend.state !== "ready" || !repo}
          active={ask.active}
          onAsk={send}
          onStop={ask.stop}
        />
      </div>
      <footer className="footer">
        <span>Public GitHub repositories, grounded & cited answers.</span>
      </footer>
      {palette && (
        <CommandPalette
          repos={reposQuery.data ?? []}
          history={ask.turns}
          onSelectRepo={setRepo}
          onNew={() => ask.hydrate([])}
          onSettings={() => setSettingsOpen(true)}
          onExport={exportConversation}
          onClose={() => setPalette(false)}
        />
      )}
    </div>
  );
}
