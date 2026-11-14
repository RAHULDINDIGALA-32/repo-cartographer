import type { Metadata } from "next";
import { AdminSessionProvider } from "@/admin/session";

export const metadata: Metadata = {
  title: "Admin · repo-cartographer",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminSessionProvider>{children}</AdminSessionProvider>;
}
