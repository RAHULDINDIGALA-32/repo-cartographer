import { AppShell } from "@/components/app-shell";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string | string[] }>;
}) {
  const params = await searchParams;
  const question = Array.isArray(params.q) ? params.q[0] : params.q;
  return <AppShell initialQuestion={question} />;
}
