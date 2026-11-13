"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth, getReady } from "@/api/client";
import { ApiError, type BackendState } from "@/api/types";

export function useBackendStatus() {
  const [state, setState] = useState<BackendState>("waking");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);

  const check = useCallback(async () => {
    const current = ++generation.current;
    const started = Date.now();
    setState("waking");
    setError(null);
    setElapsed(0);
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    try {
      let delay = 2_000;
      const deadline = started + 90_000;
      while (Date.now() < deadline && current === generation.current) {
        try {
          await getHealth();
          const ready = await getReady();
          if (ready.ok) {
            setState("ready");
            return;
          }
        } catch (caught) {
          if (caught instanceof ApiError && caught.code === "aborted") return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, delay));
        delay = Math.min(delay * 1.5, 8_000);
      }
      if (current === generation.current) {
        setState("down");
        setError("The backend did not become ready in time.");
      }
    } finally {
      window.clearInterval(timer);
    }
  }, []);

  useEffect(() => {
    void check();
    return () => {
      generation.current += 1;
    };
  }, [check]);
  useEffect(() => {
    const onFocus = () => {
      if (document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", onFocus);
    return () => document.removeEventListener("visibilitychange", onFocus);
  }, [check]);
  return { state, elapsed, error, retry: check };
}
