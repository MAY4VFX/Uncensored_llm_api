"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getMe } from "@/lib/api";
import { getToken, isAuthenticated } from "@/lib/auth";

const CREDIT_PACKAGES = [
  { name: "$5 Credits", price: "$5", credits: "5.00" },
  { name: "$20 Credits", price: "$20", credits: "20.00" },
  { name: "$50 Credits", price: "$50", credits: "50.00" },
  { name: "$100 Credits", price: "$100", credits: "100.00" },
];

const SUBSCRIPTIONS = [
  { name: "Starter", price: "$19/mo", tokens: "5M tokens", models: "Up to 14B", tier: "starter" },
  { name: "Pro", price: "$49/mo", tokens: "25M tokens", models: "All models", tier: "pro", popular: true },
  { name: "Business", price: "$149/mo", tokens: "100M tokens", models: "Priority queues", tier: "business" },
];

export default function BillingPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ credits: number; tier: string } | null>(null);

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
    <div className="max-w-5xl mx-auto px-6 py-16">
      <p className="section-label mb-4">// Billing &amp; Credits</p>
      <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-3">
        Billing<span className="text-terminal-500 animate-blink">_</span>
      </h1>
      <div className="flex items-center gap-4 text-sm font-mono text-surface-800 mb-10">
        <span>
          Balance: <span className="text-terminal-500">${user.credits.toFixed(4)}</span>
        </span>
        <span className="text-surface-400">|</span>
        <span>
          Tier: <span className="uppercase text-terminal-400">{user.tier}</span>
        </span>
      </div>

      {/* Credit Packages */}
      <p className="section-label mb-4">// Top Up Credits</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-14">
        {CREDIT_PACKAGES.map((pkg) => (
          <button
            key={pkg.name}
            className="border border-surface-400 bg-surface-100 p-6 text-center hover:border-terminal-500 hover:bg-surface-200 transition-colors"
          >
            <p className="text-2xl font-mono font-bold text-terminal-500 mb-1">{pkg.price}</p>
            <p className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900">{pkg.credits} credits</p>
          </button>
        ))}
      </div>

      {/* Subscriptions */}
      <p className="section-label mb-4">// Subscription Plans</p>
      <div className="grid md:grid-cols-3 gap-6">
        {SUBSCRIPTIONS.map((sub) => (
          <div
            key={sub.name}
            className={`border bg-surface-100 p-6 relative ${
              user.tier === sub.tier
                ? "border-terminal-500"
                : sub.popular
                ? "border-terminal-600"
                : "border-surface-400"
            }`}
          >
            {sub.popular && (
              <div className="absolute -top-3 left-4 px-3 py-0.5 bg-terminal-600 text-neutral-100 text-xs font-mono uppercase tracking-[0.2em]">
                Popular
              </div>
            )}
            <h3 className="text-lg font-mono font-bold text-neutral-100 mb-1">{sub.name}</h3>
            <p className="text-2xl font-mono font-bold text-terminal-500 mb-4">{sub.price}</p>
            <ul className="text-surface-800 text-sm font-mono space-y-2 mb-6">
              <li className="flex items-center gap-2">
                <span className="text-terminal-500">&gt;</span> {sub.tokens}
              </li>
              <li className="flex items-center gap-2">
                <span className="text-terminal-500">&gt;</span> {sub.models}
              </li>
            </ul>
            <button
              className={`w-full py-2 text-sm font-mono uppercase tracking-[0.2em] transition-colors ${
                user.tier === sub.tier
                  ? "border border-terminal-500 text-terminal-400 bg-transparent cursor-default"
                  : "btn-primary"
              }`}
              disabled={user.tier === sub.tier}
            >
              {user.tier === sub.tier ? "Current Plan" : "Subscribe"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
