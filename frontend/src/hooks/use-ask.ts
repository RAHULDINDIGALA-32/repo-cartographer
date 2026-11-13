"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { askStream } from "@/api/client";
import type { AskEvent, Citation, DoneEvent, RepoSnapshot, RetrievalEvent } from "@/api/types";

export type Turn = {
  id: string;
  repo: RepoSnapshot;
  question: string;
  answer: string;
  state: "submitting" | "searching" | "thinking" | "streaming" | "complete" | "stopped" | "error";
  citations: Citation[];
  retrieval?: RetrievalEvent;
  validation?: Record<string, unknown>;
  feedback?: -1 | 1;
  createdAt: number;
  done?: DoneEvent;
  error?: {
    code: string;
    message: string;
    retryable: boolean;
    requestId?: string;
    retryAfterSeconds?: number;
  };
};

export function useAsk(repo: RepoSnapshot | undefined, includeContext = false) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [active, setActive] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const pending = useRef(new Map<string, string>());
  const frame = useRef<number | undefined>(undefined);
  const flushTokens = useCallback(() => {
    frame.current = undefined;
    const additions = new Map(pending.current);
    pending.current.clear();
    if (!additions.size) return;
    setTurns((current) =>
      current.map((item) => {
        const text = additions.get(item.id);
        return text ? { ...item, answer: item.answer + text, state: "streaming" } : item;
      }),
    );
  }, []);
  const appendToken = useCallback(
    (id: string, text: string) => {
      pending.current.set(id, `${pending.current.get(id) ?? ""}${text}`);
      if (frame.current === undefined) frame.current = requestAnimationFrame(flushTokens);
    },
    [flushTokens],
  );
  useEffect(
    () => () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
      pending.current.clear();
    },
    [],
  );
  const hydrate = useCallback(
    (history: Turn[]) => setTurns([...history].sort((a, b) => a.createdAt - b.createdAt)),
    [],
  );
  const setFeedback = useCallback(
    (id: string, feedback: -1 | 1 | undefined) =>
      setTurns((current) => current.map((item) => (item.id === id ? { ...item, feedback } : item))),
    [],
  );

  const ask = useCallback(
    async (question: string) => {
      if (!repo || active) return;
      const id = crypto.randomUUID();
      const turn: Turn = {
        id,
        repo,
        question,
        answer: "",
        state: "submitting",
        citations: [],
        createdAt: Date.now(),
      };
      setTurns((current) => [...current, turn]);
      setActive(true);
      const update = (change: Partial<Turn>) =>
        setTurns((current) =>
          current.map((item) => (item.id === id ? { ...item, ...change } : item)),
        );
      const abort = new AbortController();
      controller.current = abort;
      try {
        for await (const event of askStream(
          repo.id,
          question,
          { include_context: includeContext },
          abort.signal,
        ))
          consumeEvent(event, update, (text) => appendToken(id, text));
      } catch (caught) {
        const error = caught as {
          code?: string;
          message?: string;
          retryable?: boolean;
          requestId?: string;
          retryAfterSeconds?: number;
        };
        update({
          state: "error",
          error: {
            code: error.code ?? "unknown",
            message: error.message ?? "Something went wrong.",
            retryable: error.retryable ?? false,
            requestId: error.requestId,
            retryAfterSeconds: error.retryAfterSeconds,
          },
        });
      } finally {
        controller.current = null;
        setActive(false);
      }
    },
    [active, appendToken, includeContext, repo],
  );

  const stop = useCallback(() => {
    controller.current?.abort();
    setTurns((current) =>
      current.map((turn) =>
        turn.state !== "complete" && turn.state !== "error" ? { ...turn, state: "stopped" } : turn,
      ),
    );
    setActive(false);
  }, []);
  return { turns, active, ask, stop, hydrate, setFeedback };
}

function consumeEvent(
  event: AskEvent,
  update: (change: Partial<Turn>) => void,
  append: (text: string) => void,
) {
  if (event.kind === "retrieval") update({ state: "searching", retrieval: event });
  else if (event.kind === "status") update({ state: "thinking" });
  else if (event.kind === "token") append(event.text);
  else if (event.kind === "citations")
    update({ citations: event.citations, validation: event.validation });
  else if (event.kind === "done") update({ state: "complete", done: event });
  else if (event.kind === "error")
    update({
      state: "error",
      error: {
        code: event.code ?? "unknown",
        message: event.message ?? "The answer could not be completed.",
        retryable: event.retryable ?? false,
        requestId: event.request_id,
      },
    });
}
