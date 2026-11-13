import { AppShell } from "@/components/app-shell";

export default async function RepositoryPage({ params }: { params: Promise<{ repoId: string }> }) {
  const { repoId } = await params;
  const parsed = Number(repoId);
  return <AppShell requestedRepoId={Number.isInteger(parsed) && parsed > 0 ? parsed : undefined} />;
}
