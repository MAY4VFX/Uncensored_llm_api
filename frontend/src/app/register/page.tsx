"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { register } from "@/lib/api";
import { setToken } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const { access_token } = await register(email, password);
      setToken(access_token);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message);
    }
    setLoading(false);
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <p className="section-label mb-6">// Registration</p>
        <h1 className="text-2xl font-mono font-bold text-neutral-100 mb-8">
          Create Account<span className="text-terminal-500 animate-blink">_</span>
        </h1>

        {error && (
          <div className="border border-red-900 bg-red-950/30 text-red-400 text-xs font-mono p-3 mb-6">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2 block">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="input-field w-full"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2 block">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className="input-field w-full"
              placeholder="Min 8 characters"
            />
          </div>
          <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
            {loading ? "Creating account..." : "Create Account"}
          </button>
        </form>

        <p className="text-surface-800 text-xs font-mono text-center mt-8">
          Already have an account?{" "}
          <Link href="/login" className="text-terminal-400 hover:text-terminal-300 transition-colors">Sign In</Link>
        </p>
      </div>
    </div>
  );
}
