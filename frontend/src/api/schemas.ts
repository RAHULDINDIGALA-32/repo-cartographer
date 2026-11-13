import { z } from "zod";

const citation = z
  .object({
    index: z.number(),
    chunk_id: z.number(),
    path: z.string(),
    start_line: z.number(),
    end_line: z.number(),
    commit_sha: z.string().nullable().optional(),
    permalink: z.string().url().nullable().optional(),
    symbol: z.string().nullable().optional(),
    snippet: z.string().optional(),
    snippet_truncated: z.boolean().optional(),
  })
  .passthrough();

const staleness = z
  .object({
    indexed_sha: z.string().nullable().optional(),
    indexed_at: z.string().nullable().optional(),
    remote_sha: z.string().nullable().optional(),
    remote_checked_at: z.string().nullable().optional(),
    is_stale: z.boolean().nullable().optional(),
    sync: z.string().nullable().optional(),
    message: z.string().nullable().optional(),
  })
  .passthrough();

export const eventSchemas = {
  retrieval: z
    .object({
      kind: z.literal("retrieval"),
      count: z.number().optional(),
      kept: z.number().optional(),
      top_score: z.number().nullable().optional(),
      indexed_sha: z.string().nullable().optional(),
    })
    .passthrough(),
  status: z.object({ kind: z.literal("status"), text: z.string().optional() }).passthrough(),
  token: z.object({ kind: z.literal("token"), text: z.string() }).passthrough(),
  citations: z
    .object({
      kind: z.literal("citations"),
      citations: z.array(citation),
      validation: z.record(z.string(), z.unknown()).optional(),
    })
    .passthrough(),
  done: z
    .object({
      kind: z.literal("done"),
      query_log_id: z.number().nullable().optional(),
      staleness: staleness.nullable().optional(),
      degraded: z.array(z.string()).optional(),
    })
    .passthrough(),
  error: z
    .object({
      kind: z.literal("error"),
      code: z.string().optional(),
      message: z.string().optional(),
      retryable: z.boolean().optional(),
      request_id: z.string().optional(),
    })
    .passthrough(),
} as const;

export function parseEvent(kind: string, data: unknown) {
  const schema = eventSchemas[kind as keyof typeof eventSchemas];
  if (!schema) return null;
  const result = schema.safeParse(data);
  if (!result.success) {
    if (process.env.NODE_ENV === "development")
      console.warn("Unexpected SSE event", kind, result.error);
    return null;
  }
  return result.data;
}
