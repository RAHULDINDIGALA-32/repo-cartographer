"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Pin, RefreshCw } from "lucide-react";
import { adminReady, adminRepo, createRepo, deleteRepo, syncRepo } from "@/api/admin";
import type { AdminJob, RepoDetail, Repository } from "@/api/types";
import { ApiError } from "@/api/types";
import { useAdminSession } from "@/admin/session";
import { AdminShell } from "@/components/admin-shell";
import { isGitHubRepoInput } from "@/admin/format";

function short(value?: string | null) {
  return value ? value.slice(0, 7) : "—";
}
function age(value?: string | null) {
  return value
    ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "unknown";
}
function repoName(url: string) {
  return url.replace(/^https?:\/\/github\.com\//, "").replace(/\/$/, "");
}
function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "The operation failed.";
}

export default function AdminReposPage() {
  const session = useAdminSession();
  const router = useRouter();
  const [repos, setRepos] = useState<Repository[]>([]);
  const [details, setDetails] = useState<Record<number, RepoDetail>>({});
  const [jobs, setJobs] = useState<Record<number, AdminJob[]>>({});
  const [url, setUrl] = useState("");
  const [enqueue, setEnqueue] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [worker, setWorker] = useState<{
    enabled?: boolean;
    configured?: boolean;
    reason?: string;
  }>({});
  const [urlError, setUrlError] = useState("");
  const refresh = useCallback(async () => {
    const values = await session.adminFetch<Repository[]>("/v1/repos");
    setRepos(values);
    const loaded = await Promise.all(
      values.map(async (repo) => [repo.id, await adminRepo(session.key!, repo.id)] as const),
    );
    setDetails(Object.fromEntries(loaded));
  }, [session]);
  useEffect(() => {
    if (!session.isAdmin) return;
    void refresh().catch((error) => setMessage(errorMessage(error)));
    void adminReady()
      .then((value) =>
        setWorker({
          enabled: value.worker_enabled,
          configured: value.worker_configured,
          reason: value.worker_reason,
        }),
      )
      .catch(() => undefined);
  }, [refresh, session.isAdmin]);
  useEffect(() => {
    const active = repos.filter(
      (repo) =>
        repo.status === "indexing" ||
        jobs[repo.id]?.some((job) => job.status === "pending" || job.status === "running"),
    );
    if (!active.length || document.visibilityState === "hidden") return;
    let stopped = false;
    const poll = async () => {
      const values = await Promise.all(
        active.map(
          async (repo) =>
            [repo.id, await session.adminFetch<AdminJob[]>(`/v1/repos/${repo.id}/jobs`)] as const,
        ),
      );
      if (!stopped) setJobs((old) => ({ ...old, ...Object.fromEntries(values) }));
    };
    void poll();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void poll();
    }, 2500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [repos, jobs, session]);
  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!isGitHubRepoInput(url)) {
      setUrlError("Enter a valid GitHub URL or owner/name, for example pallets/flask.");
      return;
    }
    setUrlError("");
    setBusy(true);
    setMessage("");
    try {
      await createRepo(session.key!, { url: url.trim(), enqueue, public: true });
      setUrl("");
      await refresh();
      setMessage("Repository registered.");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const sync = async (repo: Repository) => {
    setMessage("");
    try {
      await syncRepo(session.key!, repo.id);
      await refresh();
      setMessage(`Sync queued for ${repoName(repo.url)}.`);
    } catch (error) {
      setMessage(errorMessage(error));
    }
  };
  const remove = async (repo: Repository) => {
    if (repo.pinned) {
      setMessage("Pinned repositories cannot be deleted without an explicit override.");
      return;
    }
    const typed = window.prompt(`Type "${repoName(repo.url)}" to delete this repository.`);
    if (typed !== repoName(repo.url)) return;
    try {
      await deleteRepo(session.key!, repo.id);
      await refresh();
    } catch (error) {
      setMessage(errorMessage(error));
    }
  };
  if (!session.ready) return null;
  if (!session.isAdmin) {
    router.replace("/admin");
    return null;
  }
  return (
    <AdminShell>
      <div className="admin-title">
        <div>
          <span className="eyebrow">OPERATIONS</span>
          <h1>Repositories</h1>
          <p>Manage indexing, freshness, and incremental-sync cost.</p>
        </div>
        <button
          className="text-button"
          onClick={() => void refresh()}
          style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
        >
          <RefreshCw size={14} />
          <span>Refresh</span>
        </button>
      </div>
      {!worker.enabled && (
        <div className="notice">
          <strong>Worker disabled on this API process.</strong>
          <br />
          Queued syncs will remain pending until a worker is started
          {worker.reason ? ` (${worker.reason})` : ""}.
        </div>
      )}
      {message && (
        <div className="notice" role="status">
          {message}
        </div>
      )}
      <form className="admin-card add-repo" onSubmit={add}>
        <label>
          GitHub repository URL
          <input
            aria-invalid={Boolean(urlError)}
            value={url}
            onChange={(event) => {
              const value = event.target.value;
              setUrl(value);
              if (!value || isGitHubRepoInput(value)) setUrlError("");
            }}
            onBlur={() => {
              if (url && !isGitHubRepoInput(url))
                setUrlError("Enter a valid GitHub URL or owner/name, for example pallets/flask.");
            }}
            placeholder="https://github.com/owner/repository"
          />
          {urlError && (
            <small className="field-error" role="alert">
              {urlError}
            </small>
          )}
        </label>
        <label className="check-row add-repo-check">
          <input
            type="checkbox"
            checked={enqueue}
            onChange={(event) => setEnqueue(event.target.checked)}
          />{" "}
          Start indexing now
        </label>
        <button className="send" disabled={busy || !url.trim()}>
          {busy ? "Registering" : "Add repository"}
        </button>
      </form>
      <section className="admin-list">
        {repos.length === 0 ? (
          <div className="admin-card empty-state">
            <h2>No repositories</h2>
            <p>Add a repository to begin.</p>
          </div>
        ) : (
          repos.map((repo) => (
            <RepoCard
              key={repo.id}
              repo={repo}
              detail={details[repo.id]}
              jobs={jobs[repo.id] ?? []}
              onSync={() => void sync(repo)}
              onDelete={() => void remove(repo)}
              onJobs={() => router.push(`/admin/repos/${repo.id}/jobs`)}
            />
          ))
        )}
      </section>
    </AdminShell>
  );
}

function RepoCard({
  repo,
  detail,
  jobs,
  onSync,
  onDelete,
  onJobs,
}: {
  repo: Repository;
  detail?: RepoDetail;
  jobs: AdminJob[];
  onSync: () => void;
  onDelete: () => void;
  onJobs: () => void;
}) {
  const latest = detail?.runs?.[0] ?? {};
  const active = jobs.find((job) => job.status === "pending" || job.status === "running");
  const result = (latest.stats ?? latest.result ?? {}) as Record<string, unknown>;
  const reuse = Number(result.chunks_reused ?? latest.chunks_reused ?? 0);
  const embedded = Number(result.chunks_embedded ?? latest.chunks_embedded ?? 0);
  const ratio = reuse + embedded ? Math.round((reuse / (reuse + embedded)) * 100) : null;
  return (
    <article className="repo-admin-card">
      <div className="repo-admin-head">
        <a href={repo.url} target="_blank" rel="noopener noreferrer" className="repo-title">
          {repoName(repo.url)} ↗
        </a>
        <span className={`status-badge status-${repo.status}`}>{repo.status}</span>
        {repo.pinned && (
          <span
            className="meta-chip"
            style={{ display: "inline-flex", alignItems: "center", gap: "5px" }}
          >
            <Pin size={14} />
            Pinned
          </span>
        )}
        <span className="meta-chip">{repo.public ? "Public" : "Hidden"}</span>
      </div>
      <div className="repo-facts">
        <span>
          Indexed <b className="mono">{short(repo.indexed_sha)}</b>
        </span>
        <span>{age(repo.indexed_at)}</span>
        <span className={repo.staleness ? "meta-chip stale" : "meta-chip fresh"}>
          {repo.staleness
            ? "Newer commit known"
            : repo.staleness === false
              ? "Fresh"
              : "Freshness unknown"}
        </span>
        {ratio !== null && <span>Reuse {ratio}%</span>}
      </div>
      {active && (
        <div className="job-inline">
          <strong>{active.status}</strong> · job #{active.id} · {active.trigger ?? "manual"}
        </div>
      )}
      <div className="repo-actions">
        <button className="text-button" onClick={onSync}>
          Sync now
        </button>
        <button className="text-button" onClick={onJobs}>
          View jobs
        </button>
        <button className="text-button danger" onClick={onDelete}>
          Delete
        </button>
      </div>
    </article>
  );
}
