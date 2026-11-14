import type { Metadata } from "next";
import { Toaster } from "sonner";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "repo-cartographer — Ask any codebase",
  description: "Grounded answers about public GitHub repositories, with citations.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
        <Toaster
          position="bottom-right"
          theme="dark"
          toastOptions={{
            classNames: {
              toast: "my-toast",
              title: "my-toast-title",
              description: "my-toast-description",
            },
          }}
        />
      </body>
    </html>
  );
}
