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
  stack: ["FastAPI", "Postgres + pgvector", "Hybrid retrieval", "Provider gateway", "Next.js"],
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
