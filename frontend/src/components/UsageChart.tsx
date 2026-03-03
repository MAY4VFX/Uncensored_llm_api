"use client";

import { useEffect, useState } from "react";
import { getUsage } from "@/lib/api";
import { getToken } from "@/lib/auth";

export default function UsageChart() {
  const [usage, setUsage] = useState<{
    total_tokens_in: number;
    total_tokens_out: number;
    total_cost: number;
    credits_remaining: number;
    recent_usage: Array<{
      model_slug: string;
      tokens_in: number;
      tokens_out: number;
      cost: number;
      created_at: string;
    }>;
  } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    getUsage(token).then(setUsage).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-red-500 font-mono text-sm">{error}</p>;
  if (!usage) return <p className="text-surface-800 font-mono text-sm">Loading usage data...</p>;

  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-surface-300 border border-surface-300 mb-8">
        {[
          { label: "Credits", value: `$${usage.credits_remaining.toFixed(4)}` },
          { label: "Total Cost", value: `$${usage.total_cost.toFixed(4)}` },
          { label: "Tokens In", value: usage.total_tokens_in.toLocaleString() },
          { label: "Tokens Out", value: usage.total_tokens_out.toLocaleString() },
        ].map((stat) => (
          <div key={stat.label} className="bg-surface-50 p-5">
            <p className="text-[10px] font-mono uppercase tracking-widest text-surface-800 mb-1">{stat.label}</p>
            <p className="text-xl font-mono text-terminal-400">{stat.value}</p>
          </div>
        ))}
      </div>

      <p className="section-label mb-4">// Recent requests</p>
      <div className="overflow-x-auto border border-surface-400">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="text-surface-800 text-left border-b border-surface-400">
              <th className="p-3 uppercase tracking-widest">Model</th>
              <th className="p-3 uppercase tracking-widest">In</th>
              <th className="p-3 uppercase tracking-widest">Out</th>
              <th className="p-3 uppercase tracking-widest">Cost</th>
              <th className="p-3 uppercase tracking-widest">Time</th>
            </tr>
          </thead>
          <tbody>
            {usage.recent_usage.map((entry, i) => (
              <tr key={i} className="border-t border-surface-300 text-neutral-400 hover:bg-surface-100 transition-colors">
                <td className="p-3 text-terminal-400">{entry.model_slug}</td>
                <td className="p-3">{entry.tokens_in.toLocaleString()}</td>
                <td className="p-3">{entry.tokens_out.toLocaleString()}</td>
                <td className="p-3">${entry.cost.toFixed(6)}</td>
                <td className="p-3 text-surface-800">{new Date(entry.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {usage.recent_usage.length === 0 && (
              <tr>
                <td colSpan={5} className="p-6 text-surface-700 text-center">
                  No usage yet. Make your first API call.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
