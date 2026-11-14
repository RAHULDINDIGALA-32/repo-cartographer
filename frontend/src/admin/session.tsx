"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { adminRequest, adminValidate } from "@/api/admin";
import { ApiError } from "@/api/types";

type AdminSessionValue = {
  key: string | null;
  isAdmin: boolean;
  ready: boolean;
  signIn: (key: string, remember: boolean) => Promise<void>;
  signOut: () => void;
  adminFetch: <T>(path: string, options?: RequestInit & { timeoutMs?: number }) => Promise<T>;
};

const AdminSessionContext = createContext<AdminSessionValue | null>(null);
const STORAGE_KEY = "repo-cartographer.admin-tab";
const IDLE_MS = 30 * 60 * 1000;

export function AdminSessionProvider({ children }: { children: React.ReactNode }) {
  const [key, setKey] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setKey(sessionStorage.getItem(STORAGE_KEY));
    setReady(true);
  }, []);
  useEffect(() => {
    if (!key) return;
    const timer = window.setTimeout(() => {
      setKey(null);
      sessionStorage.removeItem(STORAGE_KEY);
      toast.info("Admin session expired.");
    }, IDLE_MS);
    return () => window.clearTimeout(timer);
  }, [key]);
  useEffect(() => {
    const clear = () => {
      setKey(null);
      sessionStorage.removeItem(STORAGE_KEY);
    };
    window.addEventListener("repo-cartographer:admin-unauthorized", clear);
    return () => window.removeEventListener("repo-cartographer:admin-unauthorized", clear);
  }, []);
  const value = useMemo<AdminSessionValue>(
    () => ({
      key,
      isAdmin: Boolean(key),
      ready,
      signIn: async (candidate, remember) => {
        const clean = candidate.trim();
        if (!clean)
          throw new ApiError({ code: "validation_error", message: "Enter the admin API key." });
        await adminValidate(clean);
        setKey(clean);
        if (remember) sessionStorage.setItem(STORAGE_KEY, clean);
        else sessionStorage.removeItem(STORAGE_KEY);
      },
      signOut: () => {
        setKey(null);
        sessionStorage.removeItem(STORAGE_KEY);
      },
      adminFetch: async <T,>(path: string, options?: RequestInit & { timeoutMs?: number }) => {
        if (!key)
          throw new ApiError({
            code: "unauthorized",
            message: "Admin sign-in required.",
            status: 401,
          });
        try {
          return await adminRequest<T>(key, path, options);
        } catch (error) {
          if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
            setKey(null);
            sessionStorage.removeItem(STORAGE_KEY);
            toast.error("Admin authorization expired.");
          }
          throw error;
        }
      },
    }),
    [key, ready],
  );
  return <AdminSessionContext.Provider value={value}>{children}</AdminSessionContext.Provider>;
}

export function useAdminSession() {
  const value = useContext(AdminSessionContext);
  if (!value) throw new Error("useAdminSession must be used inside AdminSessionProvider");
  return value;
}
