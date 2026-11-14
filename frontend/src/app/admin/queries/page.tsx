"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { adminQueries, adminRepos } from "@/api/admin";
import type { AdminQueryRow, Repository } from "@/api/types";
import { useAdminSession } from "@/admin/session";
import { relative, duration, integer } from "@/admin/format";
import { AdminShell } from "@/components/admin-shell";

export default function AdminQueriesPage() {
  const session = useAdminSession();
  const router = useRouter();
  const [rows, setRows] = useState<AdminQueryRow[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [since, setSince] = useState("24h");
  const [repoId, setRepoId] = useState("");
  const [outcome, setOutcome] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(
    async (append = false) => {
      try {
        const page = await adminQueries(session.key!, {
          since,
          repoId: repoId ? Number(repoId) : undefined,
          outcome: outcome || undefined,
          cursor: append ? cursor : null,
        });
        setRows((old) => (append ? [...old, ...page.items] : page.items));
        setNext(page.next_cursor);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not load queries.");
      }
    },
    [cursor, outcome, repoId, session.key, since],
  );
  useEffect(() => {
    if (!session.isAdmin) return;
    void load();
    void adminRepos(session.key!)
      .then(setRepos)
      .catch(() => undefined);
  }, [load, session.isAdmin, session.key]);
  const filtered = useMemo(
    () => rows.filter((row) => row.question.toLowerCase().includes(text.toLowerCase())),
    [rows, text],
  );
  if (!session.ready) return null;
  return (
    <AdminShell>
      <div className="admin-title">
        <div>
          <span className="eyebrow">OBSERVABILITY</span>
          <h1>Query explorer</h1>
          <p>Inspect logged answers and open their RAG traces.</p>
        </div>
        <button className="meta-action" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      <div className="admin-filters">
        <select value={since} onChange={(event) => setSince(event.target.value)}>
          <option value="24h">24 hours</option>
          <option value="7d">7 days</option>
          <option value="30d">30 days</option>
        </select>
        <select value={repoId} onChange={(event) => setRepoId(event.target.value)}>
          <option value="">All repositories</option>
          {repos.map((repo) => (
            <option value={repo.id} key={repo.id}>
              {repo.url.replace(/^https?:\/\/github\.com\//, "")}
            </option>
          ))}
        </select>
        <input
          placeholder="Filter loaded questions"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <select value={outcome} onChange={(event) => setOutcome(event.target.value)}>
          <option value="">All outcomes</option>
          <option value="provider_error">provider_error</option>
          <option value="generation_error">generation_error</option>
        </select>
      </div>
      {error && <div className="alert">{error}</div>}
      <div className="admin-card table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Repository</th>
              <th>Question</th>
              <th>Outcome</th>
              <th>Latency</th>
              <th>Tokens</th>
              <th>Citations</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <QueryRow
                key={row.id}
                row={row}
                repo={repos.find((item) => item.id === row.repo_id)}
                onClick={() => router.push(`/admin/queries/${row.id}`)}
              />
            ))}
          </tbody>
        </table>
        {!filtered.length && <p className="empty-inline">No queries match this window.</p>}
        {next && (
          <button
            className="load-more"
            onClick={() => {
              setCursor(next);
              void load(true);
            }}
          >
            Load more
          </button>
        )}
      </div>
    </AdminShell>
  );
}
function QueryRow({
  row,
  repo,
  onClick,
}: {
  row: AdminQueryRow;
  repo?: Repository;
  onClick: () => void;
}) {
  const check = row.citation_check ?? {};
  return (
    <tr
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter") onClick();
      }}
    >
      <td title={new Date(row.created_at).toLocaleString()}>{relative(row.created_at)}</td>
      <td>{repo?.url.replace(/^https?:\/\/github\.com\//, "") ?? `#${row.repo_id}`}</td>
      <td className="question-preview">{row.question}</td>
      <td>
        <span className={`status-badge ${row.outcome === "ok" ? "status-ready" : "status-error"}`}>
          {row.outcome}
        </span>
      </td>
      <td>{duration(row.latencies_ms?.total)}</td>
      <td>{integer((row.tokens_in ?? 0) + (row.tokens_out ?? 0))}</td>
      <td>
        {check.uncited_answer
          ? "uncited"
          : Array.isArray(check.invalid) && check.invalid.length
            ? `invalid ${check.invalid.length}`
            : "valid"}
      </td>
    </tr>
  );
}
