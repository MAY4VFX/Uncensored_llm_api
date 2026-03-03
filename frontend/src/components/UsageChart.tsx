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

  if (error) return <p className="text-red-400">{error}</p>;
  if (!usage) return <p className="text-gray-400">Loading usage data...</p>;

  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <p className="text-gray-400 text-xs">Credits Remaining</p>
          <p className="text-2xl font-bold text-white">${usage.credits_remaining.toFixed(4)}</p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <p className="text-gray-400 text-xs">Total Cost</p>
          <p className="text-2xl font-bold text-white">${usage.total_cost.toFixed(4)}</p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <p className="text-gray-400 text-xs">Tokens In</p>
          <p className="text-2xl font-bold text-white">{usage.total_tokens_in.toLocaleString()}</p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
          <p className="text-gray-400 text-xs">Tokens Out</p>
          <p className="text-2xl font-bold text-white">{usage.total_tokens_out.toLocaleString()}</p>
        </div>
      </div>

      <h3 className="text-lg font-semibold text-white mb-4">Recent Requests</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-400 text-left">
              <th className="pb-2">Model</th>
              <th className="pb-2">Tokens In</th>
              <th className="pb-2">Tokens Out</th>
              <th className="pb-2">Cost</th>
              <th className="pb-2">Time</th>
            </tr>
          </thead>
          <tbody>
            {usage.recent_usage.map((entry, i) => (
              <tr key={i} className="border-t border-gray-800 text-gray-300">
                <td className="py-2">{entry.model_slug}</td>
                <td className="py-2">{entry.tokens_in.toLocaleString()}</td>
                <td className="py-2">{entry.tokens_out.toLocaleString()}</td>
                <td className="py-2">${entry.cost.toFixed(6)}</td>
                <td className="py-2">{new Date(entry.created_at).toLocaleString()}</td>
              </tr>
            ))}
            {usage.recent_usage.length === 0 && (
              <tr>
                <td colSpan={5} className="py-4 text-gray-500 text-center">
                  No usage yet. Make your first API call!
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
