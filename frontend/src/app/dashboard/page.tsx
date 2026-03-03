"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import UsageChart from "@/components/UsageChart";
import { getMe } from "@/lib/api";
import { getToken, isAuthenticated } from "@/lib/auth";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ email: string; credits: number; tier: string } | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
      return;
    }
    const token = getToken()!;
    getMe(token).then(setUser).catch(() => router.push("/login"));
  }, [router]);

  if (!user) return <div className="text-surface-800 font-mono text-sm p-8">Loading...</div>;

  return (
    <div className="max-w-7xl mx-auto px-6 py-16">
      <div className="flex items-start justify-between mb-10">
        <div>
          <p className="section-label mb-4">// Control Panel</p>
          <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-3">
            Dashboard<span className="text-terminal-500 animate-blink">_</span>
          </h1>
          <div className="flex items-center gap-4 text-sm font-mono text-surface-800">
            <span>{user.email}</span>
            <span className="text-surface-400">|</span>
            <span className="uppercase text-terminal-400">{user.tier}</span>
            <span className="text-surface-400">|</span>
            <span>
              <span className="text-terminal-500">${user.credits.toFixed(4)}</span> credits
            </span>
          </div>
        </div>
        <div className="flex gap-3">
          <Link href="/dashboard/api-keys" className="btn-secondary text-sm">
            API Keys
          </Link>
          <Link href="/dashboard/billing" className="btn-primary text-sm">
            Add Credits
          </Link>
        </div>
      </div>

      <div className="border border-surface-400 bg-surface-100 p-6">
        <p className="section-label mb-4">// Usage Metrics</p>
        <UsageChart />
      </div>
    </div>
  );
}
