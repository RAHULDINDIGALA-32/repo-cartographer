"use client";

import { Copy, ExternalLink } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";
import type { Citation } from "@/api/types";
import type { Turn as TurnModel } from "@/hooks/use-ask";
import { Markdown } from "./markdown";

function messageFor(code: string) {
  if (code === "validation_error") return "Please check the question and try again.";
  if (code === "rate_limited")
    return "You have reached the request limit. Please wait before trying again.";
  if (code === "budget_exhausted")
    return "The daily answer budget has been reached. Please try again later.";
  if (code === "server_busy") return "The service is busy right now. Please try again shortly.";
  if (code === "repo_not_ready")
    return "This repository is still being indexed. Choose another ready repository or try later.";
  if (code.startsWith("provider_") || code.startsWith("generation_"))
    return "The answer provider could not complete this request.";
  if (code === "connection_lost" || code === "network_error")
    return "Connection lost while receiving the answer.";
  return "Something went wrong while answering your question.";
}

function freshness(turn: TurnModel) {
  const stale = turn.done?.staleness?.is_stale;
  if (stale === true) return ["stale", "Newer commit available · sync queued"];
  if (stale === false)
    return ["fresh", `Up to date · ${(turn.done?.staleness?.indexed_sha ?? "").slice(0, 7)}`];
  return ["", "Freshness unknown"];
}

export function Turn({ turn, onRetry }: { turn: TurnModel; onRetry: () => void }) {
  const cited = useMemo(() => turn.citations.map((item) => item.index), [turn.citations]);
  const copy = async () => {
    await navigator.clipboard.writeText(turn.answer);
    toast.success("Answer copied");
  };
  const [freshClass, freshText] = freshness(turn);
  return (
    <article className="turn">
      <div className="question">{turn.question}</div>
      <div className="answer" aria-busy={turn.state === "streaming" || turn.state === "thinking"}>
        {!turn.answer && turn.state !== "error" && turn.state !== "stopped" && (
          <p className="text-muted">
            {turn.state === "searching"
              ? "Searching the code…"
              : turn.state === "thinking"
                ? "Thinking…"
                : "Preparing an answer…"}
          </p>
        )}
        {turn.answer && <Markdown text={turn.answer} citations={cited} />}
        {turn.state === "stopped" && (
          <p className="text-muted">Stopped. The partial answer is preserved.</p>
        )}
        {turn.error && (
          <div className="alert" role="alert">
            <strong>{messageFor(turn.error.code)}</strong>
            {turn.error.retryAfterSeconds ? ` Try again in ${turn.error.retryAfterSeconds}s.` : ""}
            {turn.error.retryable && (
              <>
                <br />
                <button type="button" onClick={onRetry}>
                  Try again
                </button>
              </>
            )}
          </div>
        )}
      </div>
      {turn.citations.length > 0 && (
        <section className="sources" aria-label="Sources">
          <h2>Sources</h2>
          {turn.citations.map((source: Citation) => (
            <div
              className="source"
              id={`source-${source.index}`}
              key={`${source.index}-${source.chunk_id}`}
              tabIndex={0}
            >
              <span className="source-index">{source.index}</span>
              <span className="source-path mono" title={source.path}>
                {source.path}
              </span>
              <span className="source-lines">
                L{source.start_line}–{source.end_line}
              </span>
              {source.symbol && <span className="source-lines">{source.symbol}</span>}
              {source.permalink && (
                <a
                  href={source.permalink}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Open source ${source.path}`}
                >
                  <ExternalLink size={14} aria-hidden />
                </a>
              )}
            </div>
          ))}
        </section>
      )}
      {turn.state === "complete" && (
        <div className="meta">
          <span className={`meta-chip ${freshClass}`}>{freshText}</span>
          {turn.done?.degraded?.length ? (
            <span className="meta-chip bad" title={turn.done.degraded.join(", ")}>
              Degraded
            </span>
          ) : null}
          <button className="icon-button" type="button" aria-label="Copy answer" onClick={copy}>
            <Copy size={14} aria-hidden />
          </button>
          <details className="details">
            <summary>Details</summary>
            <div className="details-grid">
              <span>Provider: {turn.done?.provider ?? "—"}</span>
              <span>Tokens: {turn.done?.tokens_out ?? "—"}</span>
              <span>Request: {turn.done?.query_log_id ?? "—"}</span>
            </div>
          </details>
        </div>
      )}
    </article>
  );
}
