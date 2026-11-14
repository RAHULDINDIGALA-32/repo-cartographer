"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAdminSession } from "@/admin/session";
import { API_BASE_URL } from "@/api/config";
import { AdminSignIn } from "./admin-sign-in";
import { BRAND_NAME } from "@/api/config";

export function AdminShell({ children }: { children: React.ReactNode }) {
  const session = useAdminSession();
  const { signOut } = session;
  const pathname = usePathname();
  const router = useRouter();
  if (!session.ready) return null;
  if (!session.isAdmin) return <AdminSignIn />;
  const nav = [
    ["/admin/repos", "Repositories"],
    ["/admin/stats", "Stats"],
    ["/admin/queries", "Queries"],
  ] as const;
  return (
    <div className="admin-shell">
      <header className="header">
        <div className="header-inner">
          <Link className="brand" href="/">
            <div className="brand">
            <span className="brand-mark" aria-hidden>
              ◈
            </span>
            <span className="brand-name">{BRAND_NAME}</span>
          </div>
          </Link>
    
          <span className="admin-badge">Admin</span>
          <nav className="admin-nav" aria-label="Admin navigation">
            {nav.map(([href, label]) => (
              <Link className={pathname.startsWith(href) ? "active" : ""} key={href} href={href}>
                {label}
              </Link>
            ))}
          </nav>
          <span className="api-host mono" title={API_BASE_URL}>
            {new URL(API_BASE_URL).host}
          </span>
          <button
            className="text-button"
            onClick={() => {
              signOut();
              router.replace("/admin");
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="admin-main">{children}</main>
    </div>
  );
}
