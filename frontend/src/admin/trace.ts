export type TraceChunk = {
  id: number;
  path: string;
  start_line?: number;
  end_line?: number;
  symbol?: string;
  symbol_type?: string;
  token_count?: number;
};
export type NormalizedTrace = {
  analysis: Record<string, unknown>;
  degraded: string[];
  signals: Record<string, Array<Record<string, unknown>>>;
  fused: Array<Record<string, unknown>>;
  reranked: Array<Record<string, unknown>>;
  assembly: Record<string, unknown>;
  config: Record<string, unknown>;
  raw: Record<string, unknown>;
  chunks: Record<string, TraceChunk>;
};
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const rows = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> =>
        Boolean(item && typeof item === "object" && !Array.isArray(item)),
      )
    : [];
export function normalizeTrace(
  value: unknown,
  metadata: Record<string, Record<string, unknown>> = {},
): NormalizedTrace {
  const raw = record(value);
  const signals: Record<string, Array<Record<string, unknown>>> = {};
  const lists = record(raw.lists);
  for (const [name, list] of Object.entries(lists)) signals[name] = rows(list);
  if (Array.isArray(raw.dense)) signals.dense = rows((raw.dense as unknown[])[0]);
  const chunks: Record<string, TraceChunk> = {};
  for (const [key, item] of Object.entries(metadata)) {
    const id = Number(item.id ?? key);
    if (Number.isFinite(id))
      chunks[String(id)] = {
        id,
        path: String(item.path ?? `chunk ${id}`),
        start_line: Number(item.start_line) || undefined,
        end_line: Number(item.end_line) || undefined,
        symbol: typeof item.symbol === "string" ? item.symbol : undefined,
        symbol_type: typeof item.symbol_type === "string" ? item.symbol_type : undefined,
        token_count: Number(item.token_count) || undefined,
      };
  }
  return {
    analysis: record(raw.analysis),
    degraded: Array.isArray(raw.degraded)
      ? raw.degraded.filter((item): item is string => typeof item === "string")
      : [],
    signals,
    fused: rows(raw.fused),
    reranked: rows(raw.reranked),
    assembly: record(raw.assembly),
    config: record(raw.pipeline_config ?? raw.config),
    raw,
    chunks,
  };
}
export function traceObservations(trace: NormalizedTrace, citations: number[] = []) {
  const facts: string[] = [];
  const top = trace.fused[0]?.id;
  const cited = new Set(citations);
  const contextIds = new Set(Object.values(trace.chunks).map((chunk) => chunk.id));
  if (cited.size && [...cited].some((id) => !contextIds.has(id)))
    facts.push("A cited source has no resolved context metadata.");
  if (
    top != null &&
    !Object.values(trace.signals).some((list) =>
      list.some((item) => Number(item.id) === Number(top)),
    )
  )
    facts.push("The top fused result does not appear in a signal list.");
  if (
    trace.reranked.length &&
    trace.fused.length &&
    Number(trace.reranked[0]?.id) !== Number(trace.fused[0]?.id)
  )
    facts.push("The reranker changed the top result.");
  if (trace.degraded.length) facts.push(`Degraded components: ${trace.degraded.join(", ")}.`);
  const dropped = Number(trace.assembly.dropped_budget ?? 0);
  if (dropped > 0) facts.push(`Context was truncated by budget; ${dropped} blocks were dropped.`);
  if (!facts.length) facts.push("No additional derived observations were found in this trace.");
  return facts;
}
