"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { adminRepo } from "@/api/admin";
import type { AdminJob, RepoDetail } from "@/api/types";
import { useAdminSession } from "@/admin/session";
import { compactNumber, duration, integer, relative } from "@/admin/format";
import { AdminShell } from "@/components/admin-shell";

export default function JobsPage() {
  const session = useAdminSession();
  const { repoId } = useParams<{ repoId: string }>();
  const id = Number(repoId);
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [detail, setDetail] = useState<RepoDetail>();
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [values, info] = await Promise.all([
        session.adminFetch<AdminJob[]>(`/v1/repos/${id}/jobs`),
        adminRepo(session.key!, id),
      ]);
      setJobs(values);
      setDetail(info);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load jobs.");
    }
  }, [id, session]);
  useEffect(() => {
    if (!session.isAdmin || !Number.isFinite(id)) return;
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [id, load, session.isAdmin]);
  if (!session.ready) return null;
  const latest = detail?.runs?.[0] ?? {};
  const result = (latest.stats ?? latest.result ?? {}) as Record<string, unknown>;
  const reused = Number(result.chunks_reused ?? latest.chunks_reused ?? 0);
  const embedded = Number(result.chunks_embedded ?? latest.chunks_embedded ?? 0);
  const saved = Number(result.tokens_saved ?? result.estimated_tokens_saved ?? 0);
  const total = reused + embedded;
  return (
    <AdminShell>
      <div className="admin-title">
        <div>
          <span className="eyebrow">SYNC JOBS</span>
          <h1>Repository #{id}</h1>
          <p>Bounded polling pauses when this tab is hidden.</p>
        </div>
        <button
          className="text-button"
          onClick={() => void load()}
          style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}
        >
          <RefreshCw size={14} />
          <span>Refresh</span>
        </button>
      </div>
      {error && <div className="alert">{error}</div>}
      {total > 0 || saved > 0 ? (
        <section className="savings-card">
          <h2>
            Reused {total ? Math.round((reused / total) * 100) : 0}% of embeddings
            {saved ? `. About ${compactNumber(saved)} tokens saved.` : "."}
          </h2>
          <div className="segmented-bar">
            <i className="reused" style={{ width: `${total ? (reused / total) * 100 : 0}%` }} />
            <i className="embedded" style={{ width: `${total ? (embedded / total) * 100 : 0}%` }} />
          </div>
          <div className="stat-cards">
            <div className="stat-card">
              <span>Reused chunks</span>
              <strong>{integer(reused)}</strong>
            </div>
            <div className="stat-card">
              <span>Embedded chunks</span>
              <strong>{integer(embedded)}</strong>
            </div>
            <div className="stat-card">
              <span>Estimated saved</span>
              <strong>{compactNumber(saved)}</strong>
            </div>
            <div className="stat-card">
              <span>Duration</span>
              <strong>{duration(Number(latest.duration_ms))}</strong>
            </div>
          </div>
        </section>
      ) : (
        <div className="admin-card">
          <strong>No completed sync savings yet.</strong>
          <p className="text-muted">
            The next completed incremental sync will show reuse and token savings here.
          </p>
        </div>
      )}
      <section className="admin-card table-scroll">
        <h2>Job history</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Type</th>
              <th>Trigger</th>
              <th>Status</th>
              <th>Attempts</th>
              <th>Created</th>
              <th>Finished</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>{job.id}</td>
                <td>{job.type}</td>
                <td>{job.trigger}</td>
                <td>
                  <span className={`status-badge status-${job.status}`}>{job.status}</span>
                </td>
                <td>
                  {job.attempts}/{job.max_attempts}
                </td>
                <td>{relative(job.created_at)}</td>
                <td>{relative(job.finished_at)}</td>
                <td>{job.error_code ?? job.error ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </AdminShell>
  );
}
