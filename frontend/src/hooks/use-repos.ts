"use client";

import { useQuery } from "@tanstack/react-query";
import { listRepos } from "@/api/client";

export function useRepos(enabled: boolean) {
  return useQuery({
    queryKey: ["repos"],
    queryFn: ({ signal }) => listRepos(signal),
    enabled,
    refetchOnWindowFocus: false,
  });
}
