"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/api/types";
import { useAdminSession } from "@/admin/session";

export function AdminSignIn() {
  const { signIn } = useAdminSession();
  const router = useRouter();
  const [key, setKey] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(key, remember);
      router.replace("/admin/repos");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not validate the admin key.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="admin-auth">
      <form className="admin-card" onSubmit={submit}>
        <span className="eyebrow">ADMIN ACCESS</span>
        <h1>Sign in to operations</h1>
        <p>The key stays in this browser tab and is sent only to the configured API.</p>
        <label>
          Admin API key
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            autoFocus
          />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={remember}
            onChange={(event) => setRemember(event.target.checked)}
          />{" "}
          Remember for this tab
        </label>
        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}
        <button className="send" disabled={busy || !key.trim()}>
          {busy ? "Checking…" : "Continue"}
        </button>
      </form>
    </main>
  );
}
