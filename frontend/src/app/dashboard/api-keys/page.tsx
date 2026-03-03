"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import ApiKeyManager from "@/components/ApiKeyManager";
import { isAuthenticated } from "@/lib/auth";

export default function ApiKeysPage() {
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticated()) router.push("/login");
  }, [router]);

  return (
    <div className="max-w-3xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-white mb-8">API Key Management</h1>
      <ApiKeyManager />
    </div>
  );
}
