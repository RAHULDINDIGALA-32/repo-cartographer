import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "Repo Cartographer — Ask your codebase", template: "%s | Repo Cartographer" },
  description: "Grounded answers about public GitHub repositories, with citations.",
  applicationName: "Repo Cartographer",
  robots: { index: true, follow: true },
  openGraph: {
    siteName: "Repo Cartographer",
    type: "website",
    title: "Repo Cartographer",
    description: "Code questions, with receipts.",
  },
  twitter: {
    card: "summary_large_image",
    title: "Repo Cartographer",
    description: "Code questions, with receipts.",
  },
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      
    ],
    apple: [{ url: "/apple-icon", type: "image/png" }],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
