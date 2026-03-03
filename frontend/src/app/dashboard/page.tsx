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

  if (!user) return <div className="text-gray-400 p-8">Loading...</div>;

  return (
    <div className="max-w-7xl mx-auto px-4 py-12">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white">Dashboard</h1>
          <p className="text-gray-400 mt-1">
            {user.email} &middot;{" "}
            <span className="capitalize text-brand-400">{user.tier}</span> tier
          </p>
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

      <UsageChart />
    </div>
  );
}
