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

  if (!user) return <div className="text-gray-400 p-8">Loading...</div>;

  return (
    <div className="max-w-5xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-white mb-2">Billing</h1>
      <p className="text-gray-400 mb-8">
        Current balance: <span className="text-white font-semibold">${user.credits.toFixed(4)}</span>
        {" "}&middot; Tier: <span className="text-brand-400 capitalize">{user.tier}</span>
      </p>

      {/* Credit Packages */}
      <h2 className="text-xl font-semibold text-white mb-4">Top Up Credits</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-12">
        {CREDIT_PACKAGES.map((pkg) => (
          <button
            key={pkg.name}
            className="glass-card glow-border p-6 text-center hover:bg-gray-800/60 transition-colors"
          >
            <p className="text-2xl font-bold text-white mb-1">{pkg.price}</p>
            <p className="text-gray-400 text-sm">{pkg.credits} credits</p>
          </button>
        ))}
      </div>

      {/* Subscriptions */}
      <h2 className="text-xl font-semibold text-white mb-4">Subscription Plans</h2>
      <div className="grid md:grid-cols-3 gap-6">
        {SUBSCRIPTIONS.map((sub) => (
          <div
            key={sub.name}
            className={`glass-card p-6 relative ${
              sub.popular ? "border-brand-500/40" : ""
            } ${user.tier === sub.tier ? "ring-2 ring-brand-500" : ""}`}
          >
            {sub.popular && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-brand-600 text-white text-xs rounded-full">
                Popular
              </div>
            )}
            <h3 className="text-lg font-semibold text-white mb-1">{sub.name}</h3>
            <p className="text-2xl font-bold text-white mb-4">{sub.price}</p>
            <ul className="text-gray-400 text-sm space-y-2 mb-6">
              <li>{sub.tokens}</li>
              <li>{sub.models}</li>
            </ul>
            <button
              className={`w-full py-2 rounded-lg text-sm font-medium transition-colors ${
                user.tier === sub.tier
                  ? "bg-brand-500/20 text-brand-400 cursor-default"
                  : "bg-brand-600 hover:bg-brand-500 text-white"
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
