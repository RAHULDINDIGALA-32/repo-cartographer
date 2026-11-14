import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "App | Repo Cartographer",
  description: "Ask grounded questions about a public GitHub repository.",
  alternates: { canonical: "/app" },
};

export default async function AppPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string | string[] }>;
}) {
  const params = await searchParams;
  const question = Array.isArray(params.q) ? params.q[0] : params.q;
  return <AppShell initialQuestion={question} />;
}
