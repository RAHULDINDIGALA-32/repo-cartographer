"use client";

import { useEffect } from "react";
import { getHealth } from "@/api/client";

const PREWARM_KEY = "repo-cartographer.backend-prewarmed";

export function usePrewarm() {
  useEffect(() => {
    try {
      if (typeof window === "undefined" || !window.sessionStorage) return;
      if (window.sessionStorage.getItem(PREWARM_KEY)) return;
      if ("connection" in navigator) {
        const connection = (navigator as Navigator & { connection?: { saveData?: boolean } })
          .connection;
        if (connection?.saveData) return;
      }
      window.sessionStorage.setItem(PREWARM_KEY, "1");
      void getHealth().catch(() => undefined);
    } catch {
      // Private browsing and strict storage policies should not block the landing page.
    }
  }, []);
}
