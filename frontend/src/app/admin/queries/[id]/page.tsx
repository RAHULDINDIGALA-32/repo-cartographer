"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { adminQuery, adminRepo } from "@/api/admin";
import type { RepoDetail } from "@/api/types";
import { useAdminSession } from "@/admin/session";
import { normalizeTrace, traceObservations, type NormalizedTrace } from "@/admin/trace";
import { duration, integer } from "@/admin/format";
import { AdminShell } from "@/components/admin-shell";
import { citationLink, repoSnapshot } from "@/ui/links";

export default function TracePage() {
  const session = useAdminSession();
  const params = useParams<{ id: string }>();
  const [query, setQuery] = useState<Record<string, unknown>>();
  const [repo, setRepo] = useState<RepoDetail>();
  const [trace, setTrace] = useState<NormalizedTrace>();
  const [error, setError] = useState("");
  const [triage, setTriage] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (!session.isAdmin) return;
    const id = Number(params.id);
    void adminQuery(session.key!, id)
      .then(async (value) => {
        setQuery(value);
        setTrace(
          normalizeTrace(
            {
              ...((value.trace as Record<string, unknown>) ?? {}),
              pipeline_config: value.pipeline_config,
            },
            value.chunk_metadata,
          ),
        );
        if (typeof value.repo_id === "number")
          setRepo(await adminRepo(session.key!, value.repo_id));
      })
      .catch((caught) =>
        setError(caught instanceof Error ? caught.message : "Could not load trace."),
      );
  }, [params.id, session.isAdmin, session.key]);
  useEffect(() => {
    if (triage)
      localStorage.setItem(
        `repo-cartographer.triage.${params.id}`,
        JSON.stringify({ tag: triage, note, updatedAt: Date.now() }),
      );
  }, [triage, note, params.id]);
  if (!session.ready) return null;
  if (!query || !trace)
    return (
      <AdminShell>
        {error ? (
          <div className="alert">{error}</div>
        ) : (
          <div className="admin-card">Loading trace…</div>
        )}
      </AdminShell>
    );
  const observations = traceObservations(
    trace,
    Array.isArray(
      query.citation_check && (query.citation_check as Record<string, unknown>).valid_indices,
    )
      ? ((query.citation_check as Record<string, unknown>).valid_indices as number[])
      : [],
  );
  const latencies = Object.entries((query.latencies_ms as Record<string, number>) ?? {});
  const ids = new Set<number>(
    [...trace.fused, ...trace.reranked].map((item) => Number(item.id)).filter(Number.isFinite),
  );
  const snapshot = repo
    ? repoSnapshot(
        repo.repo.url,
        repo.repo.id,
        String(query.indexed_sha ?? repo.repo.indexed_sha ?? ""),
        repo.repo.indexed_at,
        repo.repo.default_branch,
      )
    : undefined;
  const chunkHref = (id: number) => {
    const chunk = trace.chunks[String(id)];
    if (!chunk || !snapshot?.url) return undefined;
    return citationLink(
      {
        index: 0,
        chunk_id: id,
        path: chunk.path,
        start_line: chunk.start_line ?? 1,
        end_line: chunk.end_line ?? chunk.start_line ?? 1,
        commit_sha: String(query.indexed_sha ?? "") || null,
      },
      snapshot,
    );
  };
  return (
    <AdminShell>
      <div className="admin-title">
        <div>
          <span className="eyebrow">TRACE #{String(query.id)}</span>
          <h1>{String(query.query ?? "Query trace")}</h1>
          <p>
            {String(query.created_at ?? "")} · indexed{" "}
            <span className="mono">{String(query.indexed_sha ?? "unknown").slice(0, 12)}</span>
          </p>
        </div>
        <span className={`status-badge ${query.error ? "status-error" : "status-ready"}`}>
          {query.error ? String(query.error) : "ok"}
        </span>
      </div>
      <section className="trace-grid">
        <TraceSection title="Timeline">
          <div className="waterfall">
            {latencies.map(([name, value]) => (
              <div className="water-row" key={name}>
                <span className="mono">{name}</span>
                <div>
                  <i
                    style={{
                      width: `${Math.min(100, (Number(value) / Math.max(...latencies.map(([, item]) => Number(item)), 1)) * 100)}%`,
                    }}
                  />
                </div>
                <b>{duration(Number(value))}</b>
              </div>
            ))}
          </div>
        </TraceSection>
        <TraceSection title="Analysis">
          <pre className="json-view">{JSON.stringify(trace.analysis, null, 2)}</pre>
        </TraceSection>
        <TraceSection title="Retrieval signals">
          <div className="trace-columns">
            {Object.entries(trace.signals).map(([name, rows]) => (
              <div key={name}>
                <h3>{name}</h3>
                {rows.slice(0, 20).map((row, index) => (
                  <div className="chunk-row" key={`${name}-${index}`}>
                    <span>#{String(row.id ?? "?")}</span>
                    <span>{trace.chunks[String(row.id)]?.path ?? "metadata unavailable"}</span>
                    <small>score {String(row.score ?? "—")}</small>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </TraceSection>
        <TraceSection title="Fusion and rerank">
          <TraceList title="Fused" rows={trace.fused} trace={trace} />
          <TraceList title="Reranked" rows={trace.reranked} trace={trace} />
        </TraceSection>
        <TraceSection title="Assembled context">
          <p>
            {integer(Number(trace.assembly.kept ?? 0))} kept ·{" "}
            {integer(Number(trace.assembly.dropped ?? 0))} dropped ·{" "}
            {integer(Number(trace.assembly.dropped_near_duplicate ?? 0))} near-duplicate
          </p>
          <div className="chunk-list">
            {[...ids].map((id) => (
              <div className="chunk-row" key={id}>
                <b>#{id}</b>
                {chunkHref(id) ? (
                  <a href={chunkHref(id)} target="_blank" rel="noopener noreferrer">
                    {trace.chunks[String(id)]?.path ?? "metadata unavailable"}
                  </a>
                ) : (
                  <span>{trace.chunks[String(id)]?.path ?? "metadata unavailable"}</span>
                )}
                <span>{trace.chunks[String(id)]?.token_count ?? "—"} tokens</span>
              </div>
            ))}
          </div>
        </TraceSection>
        <TraceSection title="Answer">
          <p>{String(query.answer ?? "No stored answer.")}</p>
          <p className="text-muted">Citation check: {JSON.stringify(query.citation_check ?? {})}</p>
        </TraceSection>
        <TraceSection title="Observations">
          <ul>
            {observations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </TraceSection>
        <TraceSection title="Triage (local only)">
          <select value={triage} onChange={(event) => setTriage(event.target.value)}>
            <option value="">Not classified</option>
            <option value="ok">ok</option>
            <option value="retrieval miss">retrieval miss</option>
            <option value="assembly miss">assembly miss</option>
            <option value="generation error">generation error</option>
          </select>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Optional note"
          />
        </TraceSection>
        <TraceSection title="Config snapshot">
          <pre className="json-view">{JSON.stringify(trace.config, null, 2)}</pre>
        </TraceSection>
        <TraceSection title="Raw trace">
          <pre className="json-view">{JSON.stringify(trace.raw, null, 2)}</pre>
        </TraceSection>
      </section>
    </AdminShell>
  );
}
function TraceSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="admin-card trace-section" open>
      <summary>
        <h2>{title}</h2>
      </summary>
      {children}
    </details>
  );
}
function TraceList({
  title,
  rows,
  trace,
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  trace: NormalizedTrace;
}) {
  return (
    <div>
      <h3>{title}</h3>
      {rows.map((row, index) => (
        <div className="chunk-row" key={`${title}-${index}`}>
          <b>{index + 1}</b>
          <span>{trace.chunks[String(row.id)]?.path ?? `chunk ${String(row.id ?? "?")}`}</span>
          <small>score {String(row.score ?? "—")}</small>
        </div>
      ))}
    </div>
  );
}
