import Link from "next/link";

export default function NotFound() {
  return (
    <main className="main empty-state">
      <h1>That page is not available</h1>
      <p>
        <Link href="/">Return to the repositories</Link>
      </p>
    </main>
  );
}
