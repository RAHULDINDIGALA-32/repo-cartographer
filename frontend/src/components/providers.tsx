"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState } from "react";
import { Toaster } from "sonner";

export function Providers({ children }: Readonly<{ children: React.ReactNode }>) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 2, staleTime: 30_000 } } }),
  );
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <QueryClientProvider client={client}>
        {children}
        <Toaster
          position="bottom-right"
          theme="system"
          duration={2200}
          closeButton={false}
          icons={{ success: null, info: null, warning: null, error: null, loading: null }}
          toastOptions={{
            classNames: {
              toast: "app-toast",
              title: "app-toast-title",
              description: "app-toast-description",
            },
          }}
        />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
