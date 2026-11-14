"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAdminSession } from "@/admin/session";
import { AdminSignIn } from "@/components/admin-sign-in";

export default function AdminPage() {
  const { isAdmin, ready } = useAdminSession();
  const router = useRouter();
  useEffect(() => {
    if (ready && isAdmin) router.replace("/admin/repos");
  }, [isAdmin, ready, router]);
  if (!ready || isAdmin) return null;
  return <AdminSignIn />;
}
