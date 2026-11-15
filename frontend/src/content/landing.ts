export const landingContent = {
  hero: {
    eyebrow: "Repository intelligence with receipts",
    title: "Ask your codebase. Verify every answer.",
    description:
      "Cited, commit-pinned answers from public GitHub repositories, with a trace that shows how each answer was built.",
  },
  steps: [
    { label: "Index", text: "Files become searchable chunks and embeddings." },
    { label: "Retrieve", text: "Dense, keyword, and symbol signals work together." },
    { label: "Answer", text: "The model answers from evidence, with citations." },
    { label: "Stay fresh", text: "Incremental syncs keep changed code current." },
  ],
  trust: [
    "Commit-pinned citations you can open in GitHub",
    "Grounded refusals when the code has no evidence",
    "Visible freshness when a repository is behind",
    "Prompt-injection hardening and bounded provider budgets",
  ],
  features: [
    ["Incremental sync", "Re-embed changed files instead of paying for the whole repository."],
    ["Evaluated retrieval", "Measure dense, sparse, and hybrid trade-offs on a hand-verified set."],
    ["Jobs with guardrails", "Postgres-backed queueing, retries, and worker health are visible."],
    ["Traceable answers", "Inspect retrieval, assembly, generation, and citation evidence."],
  ],
  numbers: [
    ["55", "embedding tokens for a one-file change in the scratch sync run"],
    ["4,268", "embedding tokens for that repository's full index"],
    ["1,387", "chunks produced from a pinned 218-file Flask repository"],
    ["21/22", "answerable Flask questions with the right file in dense top-5"],
  ],
  architecture: {
    eyebrow: "System architecture",
    title: "One store. Two tracks. A gateway in between.",
    readout:
      "A Postgres-backed RAG service: jobs keep public GitHub indexes fresh; questions take a parallel retrieval path; answers stream with citations.",
    index: [
      {
        id: "github",
        title: "Public GitHub",
        text: "Default-branch shallow clone. Files are hashed, never executed.",
      },
      {
        id: "jobs",
        title: "Job queue",
        text: "Postgres row locks, coalescing, and one running job per repository.",
      },
      {
        id: "ingest",
        title: "Chunk & embed",
        text: "AST chunks, identifier-split search text, embedding reuse by content hash.",
      },
      {
        id: "writer",
        title: "IndexWriter",
        text: "Writes chunks first, then files, then indexed_sha last.",
      },
    ],
    ask: [
      {
        id: "ui",
        title: "Ask UI",
        text: "Next.js client. Streamed SSE answers, citations, history on-device.",
      },
      {
        id: "analyze",
        title: "Query analyzer",
        text: "Rewrite, identifiers, and path hints before retrieval.",
      },
      {
        id: "retrieve",
        title: "Hybrid retrieve",
        text: "Dense + sparse + symbols, fused with RRF, then reranked.",
      },
      {
        id: "generate",
        title: "Grounded answer",
        text: "Cited generation from assembled blocks. Refuse without evidence.",
      },
    ],
    spine: {
      id: "postgres",
      title: "PostgreSQL",
      text: "repos, files, chunks (pgvector + FTS), jobs, query_logs — one datastore.",
    },
    bus: {
      id: "gateway",
      title: "Provider gateway",
      text: "Voyage embed/rerank and LLM adapters, with retries, budgets, and stats.",
    },
  },
} as const;

export const demoAnswer = {
  question: "How does Flask route an incoming request to the right view function?",
  repo: "pallets/flask",
  answer:
    "Flask matches the request path and method against its URL map, then dispatches the matching rule to the associated view function. The request context is pushed before dispatch, so the view can access request-local data. Exceptions and return values are normalized into a response before the context is released.",
  sources: [
    { path: "src/flask/app.py", lines: "L879–L921", label: "Request dispatch" },
    { path: "src/flask/sansio/app.py", lines: "L605–L635", label: "URL matching" },
  ],
} as const;

export const metricValues = [
  { count: 55, format: "plain" as const, suffix: "" },
  { count: 4268, format: "comma" as const, suffix: "" },
  { count: 1387, format: "comma" as const, suffix: "" },
  { count: 21, format: "plain" as const, suffix: "/22" },
];

export function formatMetricValue(metric: (typeof metricValues)[number], value = metric.count) {
  const rounded = Math.round(value);
  const core = metric.format === "comma" ? rounded.toLocaleString("en-US") : String(rounded);
  return `${core}${metric.suffix}`;
}
