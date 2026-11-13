import { AppShell } from "@/components/app-shell";

export default async function RepositoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ repoId: string }>;
  searchParams: Promise<{ q?: string | string[] }>;
}) {
  const { repoId } = await params;
  const query = await searchParams;
  const question = Array.isArray(query.q) ? query.q[0] : query.q;
  const parsed = Number(repoId);
  return (
    <AppShell
      requestedRepoId={Number.isInteger(parsed) && parsed > 0 ? parsed : undefined}
      initialQuestion={question}
    />
  );
}
