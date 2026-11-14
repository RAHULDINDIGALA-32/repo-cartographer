"use client";

import { useCallback, useEffect, useState } from "react";
import { adminReady, adminRepos, adminStats } from "@/api/admin";
import type { AdminStats, Repository } from "@/api/types";
import { useAdminSession } from "@/admin/session";
import { compactNumber, duration, integer, lowSample, percent, relative } from "@/admin/format";
import { AdminShell } from "@/components/admin-shell";

const windows = [
  ["24h", "24 hours"],
  ["7d", "7 days"],
  ["30d", "30 days"],
] as const;
export default function AdminStatsPage() {
  const session = useAdminSession();
  const [since, setSince] = useState("24h");
  const [repoId, setRepoId] = useState("");
  const [stats, setStats] = useState<AdminStats>();
  const [repos, setRepos] = useState<Repository[]>([]);
  const [auto, setAuto] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setError("");
      setStats(await adminStats(session.key!, since, repoId ? Number(repoId) : undefined));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load statistics.");
    }
  }, [repoId, session.key, since]);
  useEffect(() => {
    if (!session.isAdmin) return;
    void Promise.all([load(), adminRepos(session.key!), adminReady()])
      .then(([, values]) => setRepos(values))
      .catch(() => undefined);
  }, [load, session.isAdmin, session.key]);
  useEffect(() => {
    if (!auto) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [auto, load]);
  if (!session.ready) return null;
  return (
    <AdminShell>
      <div className="admin-title">
        <div>
          <span className="eyebrow">OBSERVABILITY</span>
          <h1>Stats</h1>
          <p>Operational health for the selected window.</p>
        </div>
        <div className="toolbar">
          <select value={since} onChange={(event) => setSince(event.target.value)}>
            {windows.map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
          <select value={repoId} onChange={(event) => setRepoId(event.target.value)}>
            <option value="">All repositories</option>
            {repos.map((repo) => (
              <option value={repo.id} key={repo.id}>
                {repo.url.replace(/^https?:\/\/github\.com\//, "")}
              </option>
            ))}
          </select>
          <label className="check-row">
            <input
              type="checkbox"
              checked={auto}
              onChange={(event) => setAuto(event.target.checked)}
            />{" "}
            Auto-refresh
          </label>
          <button className="meta-action" onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </div>
      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}
      {stats && <StatsContent stats={stats} repos={repos} />}
    </AdminShell>
  );
}

function StatsContent({ stats, repos }: { stats: AdminStats; repos: Repository[] }) {
  const cards = [
    ["Asks", integer(stats.asks.total)],
    [
      "Error rate",
      percent(stats.asks.total ? 1 - (stats.asks.by_outcome.ok ?? 0) / stats.asks.total : null),
    ],
    ["Citation compliance", percent(stats.citations.compliance_rate)],
    ["Tokens in", compactNumber(stats.tokens.in)],
    ["Tokens out", compactNumber(stats.tokens.out)],
    ["Feedback", `↑${stats.feedback.up} · ↓${stats.feedback.down}`],
  ];
  const stages = Object.entries(stats.latency_ms).sort(
    ([, a], [, b]) => (b.p95 ?? 0) - (a.p95 ?? 0),
  );
  const max = Math.max(...stages.map(([, value]) => value.p95 ?? 0), 1);
  const budget = (label: string, value: { used: number; limit: number }) => (
    <div className="gauge-card">
      <span>{label}</span>
      <b>
        {compactNumber(value.used)} / {compactNumber(value.limit)}
      </b>
      <div className="gauge">
        <i
          className={
            value.used / Math.max(value.limit, 1) >= 1
              ? "exhausted"
              : value.used / Math.max(value.limit, 1) >= 0.8
                ? "warning"
                : ""
          }
          style={{ width: `${Math.min(100, (value.used / Math.max(value.limit, 1)) * 100)}%` }}
        />
      </div>
    </div>
  );
  return (
    <div className="stats-grid">
      <section className="stat-cards">
        {cards.map(([label, value]) => (
          <div className="stat-card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </section>
      <section className="admin-card wide">
        <h2>Latency by stage</h2>
        {stages.length === 0 ? (
          <p className="text-muted">No latency data in this window.</p>
        ) : (
          <div className="bar-list">
            {stages.map(([name, value]) => (
              <div className="bar-row" key={name}>
                <span className="mono">{name}</span>
                <div className="bar-track">
                  <i style={{ width: `${((value.p95 ?? 0) / max) * 100}%` }} />
                </div>
                <span>
                  p50 {duration(value.p50)} · p95 {duration(value.p95)}{" "}
                  {lowSample(value.count) && <small>low sample ({value.count})</small>}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="admin-card">
        <h2>Outcomes</h2>
        <div className="outcome-list">
          {Object.entries(stats.asks.by_outcome).map(([name, count]) => (
            <div key={name}>
              <span className="status-badge">{name}</span>
              <b>{integer(count)}</b>
            </div>
          ))}
        </div>
      </section>
      <section className="admin-card">
        <h2>Citation health</h2>
        <p className="big-stat">{percent(stats.citations.compliance_rate)}</p>
        <p>
          {integer(stats.citations.ok)} compliant · {integer(stats.citations.uncited)} uncited ·{" "}
          {integer(stats.citations.invalid)} invalid · {integer(stats.citations.normalized)}{" "}
          normalized
        </p>
      </section>
      <section className="admin-card">
        <h2>Budgets</h2>
        <div className="gauge-list">
          {budget("Ask tokens", stats.budgets.ask)}
          {budget("Auto-sync tokens", stats.budgets.auto_sync)}
        </div>
      </section>
      <section className="admin-card">
        <h2>Degraded components</h2>
        {Object.keys(stats.degraded).length ? (
          <div className="outcome-list">
            {Object.entries(stats.degraded).map(([name, count]) => (
              <div key={name}>
                <span>{name}</span>
                <b>{count}</b>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-muted">No degraded components in this window.</p>
        )}
      </section>
      <section className="admin-card wide">
        <h2>Repository health</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Repository</th>
              <th>Indexed</th>
              <th>Age</th>
              <th>Freshness</th>
              <th>Reuse</th>
            </tr>
          </thead>
          <tbody>
            {stats.repos.map((item) => {
              const repo = repos.find((value) => value.id === item.id);
              return (
                <tr key={item.id}>
                  <td>{repo?.url.replace(/^https?:\/\/github\.com\//, "") ?? `#${item.id}`}</td>
                  <td className="mono">{item.indexed_sha?.slice(0, 7) ?? "—"}</td>
                  <td>{relative(item.indexed_at)}</td>
                  <td>
                    <span
                      className={`status-badge ${item.stale ? "status-error" : "status-ready"}`}
                    >
                      {item.stale ? "stale" : "fresh"}
                    </span>
                  </td>
                  <td>{item.last_reuse_ratio == null ? "—" : percent(item.last_reuse_ratio)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      <section className="admin-card">
        <h2>Jobs</h2>
        <p>By status</p>
        {Object.entries(stats.jobs.by_status).map(([name, count]) => (
          <div className="split-row" key={name}>
            <span>{name}</span>
            <b>{count}</b>
          </div>
        ))}
        <p>By trigger</p>
        {Object.entries(stats.jobs.by_trigger).map(([name, count]) => (
          <div className="split-row" key={name}>
            <span>{name}</span>
            <b>{count}</b>
          </div>
        ))}
      </section>
    </div>
  );
}
