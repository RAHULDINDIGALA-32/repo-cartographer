export type RepoStatus = "ready" | "indexing" | "error" | string;

export type Repository = {
  id: number;
  url: string;
  default_branch: string;
  status: RepoStatus;
  indexed_sha: string | null;
  indexed_at: string | null;
  pinned: boolean;
  remote_sha: string | null;
  remote_checked_at: string | null;
  public: boolean;
  examples: string[];
  staleness: boolean | null;
};

export type RepoSnapshot = {
  id: number;
  owner: string;
  name: string;
  url: string;
  defaultBranch?: string;
  indexedSha: string | null;
  indexedAt: string | null;
};

export type RepoDetail = {
  repo: Repository;
  runs: Array<Record<string, unknown>>;
  examples?: string[];
};

export type Citation = {
  index: number;
  chunk_id: number;
  path: string;
  start_line: number;
  end_line: number;
  commit_sha?: string | null;
  permalink?: string | null;
  symbol?: string | null;
  snippet?: string;
  snippet_truncated?: boolean;
};

export type Staleness = {
  indexed_sha?: string | null;
  indexed_at?: string | null;
  remote_sha?: string | null;
  remote_checked_at?: string | null;
  is_stale?: boolean | null;
  sync?: string | null;
  message?: string | null;
};

export type RetrievalEvent = {
  kind: "retrieval";
  count?: number;
  kept?: number;
  top_score?: number | null;
  indexed_sha?: string | null;
  hits?: Array<Record<string, unknown>>;
  ranked?: Array<Record<string, unknown>>;
  context?: Array<Record<string, unknown>>;
  dropped?: number;
};

export type StatusEvent = { kind: "status"; text?: string };
export type TokenEvent = { kind: "token"; text: string };
export type CitationsEvent = {
  kind: "citations";
  citations: Citation[];
  validation?: { uncited_answer?: boolean; invalid?: number[]; variants_normalized?: boolean };
};
export type DoneEvent = {
  kind: "done";
  query_log_id?: number | null;
  staleness?: Staleness | null;
  degraded?: string[];
  provider?: string;
  model?: string;
  latencies_ms?: Record<string, number>;
  tokens_in?: number | null;
  tokens_out?: number | null;
  usage_source?: string | null;
};
export type StreamErrorEvent = {
  kind: "error";
  code?: string;
  message?: string;
  retryable?: boolean;
  request_id?: string;
};
export type AskEvent =
  RetrievalEvent | StatusEvent | TokenEvent | CitationsEvent | DoneEvent | StreamErrorEvent;

export type ErrorCode =
  | "validation_error"
  | "rate_limited"
  | "budget_exhausted"
  | "server_busy"
  | "repo_not_ready"
  | "generation_empty"
  | "generation_internal"
  | "connection_lost"
  | "network_error"
  | "aborted"
  | (string & {});

export class ApiError extends Error {
  readonly code: ErrorCode;
  readonly retryable: boolean;
  readonly requestId?: string;
  readonly status?: number;
  readonly retryAfterSeconds?: number;

  constructor(args: {
    code: ErrorCode;
    message: string;
    retryable?: boolean;
    requestId?: string;
    status?: number;
    retryAfterSeconds?: number;
  }) {
    super(args.message);
    this.name = "ApiError";
    this.code = args.code;
    this.retryable = args.retryable ?? false;
    this.requestId = args.requestId;
    this.status = args.status;
    this.retryAfterSeconds = args.retryAfterSeconds;
  }
}

export type BackendState = "waking" | "ready" | "degraded" | "down";
