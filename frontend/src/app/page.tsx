import type { Metadata } from "next";
import { LandingPage } from "@/components/landing-page";

export const metadata: Metadata = {
  title: { absolute: "Repo Cartographer · Ask your codebase" },
  description: "Cited, commit-pinned answers from public GitHub repositories.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Repo Cartographer",
    description: "Code questions, with receipts.",
    type: "website",
  },
};

export default function HomePage() {
  return <LandingPage />;
}
