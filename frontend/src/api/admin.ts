import { request } from "./client";
import {
  ApiError,
  type AdminJob,
  type AdminQueryRow,
  type AdminStats,
  type RepoDetail,
  type Repository,
} from "./types";

export type AdminQueryPage = { items: AdminQueryRow[]; next_cursor: number | null };
export type AdminRepoCreate = {
  repo: Repository;
  already_existed: boolean;
  enqueue?: Record<string, unknown>;
};
export type AdminSyncResult = { job_id: number | null; created: boolean; reason: string };
export type AdminReady = {
  ok: boolean;
  worker_enabled?: boolean;
  worker_reason?: string;
  worker_heartbeat_age_seconds?: number | null;
  details?: Record<string, unknown>;
};

export async function adminRequest<T>(
  key: string,
  path: string,
  options: RequestInit & { timeoutMs?: number } = {},
) {
  try {
    return await request<T>(path, {
      ...options,
      headers: { ...(options.headers ?? {}), "X-API-Key": key },
    });
  } catch (error) {
    if (
      typeof window !== "undefined" &&
      error instanceof ApiError &&
      (error.status === 401 || error.status === 403)
    )
      window.dispatchEvent(new Event("repo-cartographer:admin-unauthorized"));
    throw error;
  }
}

export const adminValidate = (key: string) =>
  adminRequest<AdminStats>(key, "/v1/admin/stats?since=24h", { timeoutMs: 10_000 });
export const adminRepos = (key: string) => adminRequest<Repository[]>(key, "/v1/repos");
export const adminRepo = (key: string, id: number) =>
  adminRequest<RepoDetail>(key, `/v1/repos/${id}`);
export const adminJobs = (key: string, id: number) =>
  adminRequest<AdminJob[]>(key, `/v1/repos/${id}/jobs`);
export const adminStats = (key: string, since: string, repoId?: number) =>
  adminRequest<AdminStats>(
    key,
    `/v1/admin/stats?since=${encodeURIComponent(since)}${repoId ? `&repo_id=${repoId}` : ""}`,
  );
export const adminQueries = (
  key: string,
  params: {
    since: string;
    limit?: number;
    cursor?: number | null;
    repoId?: number;
    outcome?: string;
  },
) => {
  const query = new URLSearchParams({ since: params.since, limit: String(params.limit ?? 50) });
  if (params.cursor) query.set("cursor", String(params.cursor));
  if (params.repoId) query.set("repo_id", String(params.repoId));
  if (params.outcome) query.set("outcome", params.outcome);
  return adminRequest<AdminQueryPage>(key, `/v1/admin/queries?${query.toString()}`);
};
export const adminQuery = (key: string, id: number) =>
  adminRequest<
    Record<string, unknown> & { chunk_metadata?: Record<string, Record<string, unknown>> }
  >(key, `/v1/queries/${id}`);
export const adminReady = () => request<AdminReady>("/ready");
export const createRepo = (key: string, body: { url: string; enqueue: boolean; public: boolean }) =>
  adminRequest<AdminRepoCreate>(key, "/v1/repos", { method: "POST", body: JSON.stringify(body) });
export const syncRepo = (key: string, id: number, body = {}) =>
  adminRequest<AdminSyncResult>(key, `/v1/repos/${id}/sync`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const deleteRepo = (key: string, id: number, overridePin = false) =>
  adminRequest<{ deleted: boolean; repo_id: number }>(
    key,
    `/v1/repos/${id}?override_pin=${overridePin}`,
    { method: "DELETE" },
  );
