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
    <div className="max-w-3xl mx-auto px-6 py-16">
      <p className="section-label mb-4">// Credentials</p>
      <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-8">
        API Key Management<span className="text-terminal-500 animate-blink">_</span>
      </h1>
      <ApiKeyManager />
    </div>
  );
}
