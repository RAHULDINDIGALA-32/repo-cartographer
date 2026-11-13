"use client";

import { Copy, ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { postFeedback } from "@/api/client";
import type { Citation } from "@/api/types";
import type { Turn as TurnModel } from "@/hooks/use-ask";
import { citationLink } from "@/ui/links";
import { Markdown } from "./markdown";
const RetrievalInspector = dynamic(
  () => import("./retrieval-inspector").then((module) => module.RetrievalInspector),
  { ssr: false },
);
const SourceViewer = dynamic(
  () => import("./source-viewer").then((module) => module.SourceViewer),
  { ssr: false },
);

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
    return [
      "fresh",
      `Up to date · ${(turn.done?.staleness?.indexed_sha ?? turn.repo.indexedSha ?? "").slice(0, 7)}`,
    ];
  return ["", "Freshness unknown"];
}
function absoluteTime(value: number) {
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function Turn({
  turn,
  onRetry,
  onPersist,
}: {
  turn: TurnModel;
  onRetry: () => void;
  onPersist?: (turn: TurnModel) => void;
}) {
  const cited = useMemo(() => turn.citations.map((item) => item.index), [turn.citations]);
  const [viewerIndex, setViewerIndex] = useState<number>();
  const [feedback, setFeedback] = useState(turn.feedback);
  const [comment, setComment] = useState("");
  const [commentOpen, setCommentOpen] = useState(false);
  const [freshClass, freshText] = freshness(turn);
  const viewerCitation = viewerIndex === undefined ? undefined : turn.citations[viewerIndex];
  const copy = async () => {
    await navigator.clipboard.writeText(turn.answer);
    toast.success("Answer copied");
  };
  const copyMarkdown = async () => {
    const sources = turn.citations
      .map(
        (source) =>
          `[${source.index}] ${source.path}:L${source.start_line}–${source.end_line} ${citationLink(source, turn.repo, turn.done)}`,
      )
      .join("\n");
    await navigator.clipboard.writeText(
      `## ${turn.question}\n\n${turn.answer}\n\n### Sources\n${sources}`,
    );
    toast.success("Markdown copied");
  };
  const rate = async (rating: -1 | 1, text?: string) => {
    if (!turn.done?.query_log_id) return;
    const previous = feedback;
    setFeedback(rating);
    try {
      await postFeedback({
        query_log_id: turn.done.query_log_id,
        rating,
        comment: text || undefined,
      });
      onPersist?.({ ...turn, feedback: rating });
      toast.success("Feedback recorded");
    } catch {
      setFeedback(previous);
      toast.error("Feedback could not be recorded");
    }
  };
  const repoName = `${turn.repo.owner}/${turn.repo.name}`;
  return (
    <article className="turn" data-turn-id={turn.id}>
      <div className="turn-head">
        <a className="repo-chip" href={turn.repo.url} target="_blank" rel="noopener noreferrer">
          <i aria-hidden />
          {repoName} <ExternalLink size={12} aria-hidden />
        </a>
        <time title={absoluteTime(turn.createdAt)}>
          {new Date(turn.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </time>
      </div>
      <div className="question">{turn.question}</div>
      <div className="answer" aria-busy={turn.state === "streaming" || turn.state === "thinking"}>
        {!turn.answer && turn.state !== "error" && turn.state !== "stopped" && (
          <p className="text-muted">
            {turn.state === "searching"
              ? `Searching the code…${turn.retrieval?.count ? ` ${turn.retrieval.count} candidates` : ""}`
              : turn.state === "thinking"
                ? "Thinking…"
                : "Preparing an answer…"}
          </p>
        )}
        {turn.answer && (
          <Markdown
            text={turn.answer}
            citations={cited}
            onCitation={(index) => {
              const found = turn.citations.findIndex((item) => item.index === index);
              if (found >= 0) setViewerIndex(found);
            }}
          />
        )}
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
          {turn.citations.map((source: Citation, index) => (
            <div
              className="source"
              id={`source-${source.index}`}
              key={`${source.index}-${source.chunk_id}`}
              tabIndex={0}
            >
              <span className="source-index">{source.index}</span>
              <button className="source-view" type="button" onClick={() => setViewerIndex(index)}>
                <span className="source-path mono" title={source.path}>
                  {source.path}
                </span>
                <span className="source-lines">
                  L{source.start_line}–{source.end_line}
                </span>
                {source.symbol && <span className="source-lines">{source.symbol}</span>}
              </button>
              <a
                href={citationLink(source, turn.repo, turn.done)}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Open source ${source.path} on GitHub`}
              >
                <ExternalLink size={14} aria-hidden />
              </a>
            </div>
          ))}
        </section>
      )}
      {turn.retrieval && (
        <RetrievalInspector
          retrieval={turn.retrieval}
          citations={turn.citations}
          onOpen={(id) => {
            const index = turn.citations.findIndex((item) => item.chunk_id === id);
            if (index >= 0) setViewerIndex(index);
          }}
        />
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
          <button
            className="meta-action"
            type="button"
            onClick={() =>
              void navigator.clipboard.writeText(
                `${window.location.origin}/r/${turn.repo.id}?q=${encodeURIComponent(turn.question)}`,
              )
            }
          >
            Copy link
          </button>
          <button className="meta-action" type="button" onClick={() => void copyMarkdown()}>
            Copy markdown
          </button>
          <details className="details">
            <summary>How this was answered</summary>
            <div className="details-grid">
              <span>Retrieved: {turn.retrieval?.count ?? "—"}</span>
              <span>Kept: {turn.retrieval?.kept ?? "—"}</span>
              <span>Cited: {turn.citations.length}</span>
              <span>Provider: {turn.done?.provider ?? "—"}</span>
              <span>First token: {turn.done?.latencies_ms?.first_visible_token ?? "—"} ms</span>
              <span>Total: {turn.done?.latencies_ms?.total ?? "—"} ms</span>
              <span>
                Tokens: {turn.done?.tokens_out ?? "—"} ({turn.done?.usage_source ?? "unknown"})
              </span>
              <span>Request: {turn.done?.query_log_id ?? "—"}</span>
            </div>
          </details>
          <span className="feedback">
            <button
              className={feedback === 1 ? "selected" : ""}
              type="button"
              aria-label="Helpful answer"
              onClick={() => void rate(1)}
            >
              <ThumbsUp size={14} />
            </button>
            <button
              className={feedback === -1 ? "selected" : ""}
              type="button"
              aria-label="Unhelpful answer"
              onClick={() => {
                setCommentOpen(true);
                setFeedback(-1);
              }}
            >
              <ThumbsDown size={14} />
            </button>
          </span>
        </div>
      )}
      {commentOpen && (
        <div className="feedback-comment">
          <textarea
            maxLength={280}
            placeholder="What could be improved?"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <button
            type="button"
            onClick={() => {
              void rate(-1, comment);
              setCommentOpen(false);
            }}
          >
            Send
          </button>
          <button
            type="button"
            onClick={() => {
              void rate(-1);
              setCommentOpen(false);
            }}
          >
            Skip
          </button>
        </div>
      )}
      {viewerCitation && (
        <SourceViewer
          citation={viewerCitation}
          repo={turn.repo}
          done={turn.done}
          onClose={() => setViewerIndex(undefined)}
          onPrevious={() =>
            setViewerIndex((viewerIndex! - 1 + turn.citations.length) % turn.citations.length)
          }
          onNext={() => setViewerIndex((viewerIndex! + 1) % turn.citations.length)}
        />
      )}
    </article>
  );
}
