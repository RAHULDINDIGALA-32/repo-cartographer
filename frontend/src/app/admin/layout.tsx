import type { Metadata } from "next";
import { AdminSessionProvider } from "@/admin/session";

export const metadata: Metadata = {
  title: { absolute: "Repo Cartographer · Admin" },
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminSessionProvider>{children}</AdminSessionProvider>;
}
