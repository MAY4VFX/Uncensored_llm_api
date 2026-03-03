"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { login } from "@/lib/api";
import { setToken } from "@/lib/auth";

export default function LoginPage() {
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
      const { access_token } = await login(email, password);
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
        <p className="section-label mb-6">// Authentication</p>
        <h1 className="text-2xl font-mono font-bold text-neutral-100 mb-8">
          Sign In<span className="text-terminal-500 animate-blink">_</span>
        </h1>

        {error && (
          <div className="border border-red-900 bg-red-950/30 text-red-400 text-xs font-mono p-3 mb-6">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs font-mono uppercase tracking-widest text-surface-800 mb-2 block">Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="input-field w-full" placeholder="you@example.com" />
          </div>
          <div>
            <label className="text-xs font-mono uppercase tracking-widest text-surface-800 mb-2 block">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="input-field w-full" placeholder="Min 8 characters" />
          </div>
          <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
            {loading ? "Authenticating..." : "Sign In"}
          </button>
        </form>

        <p className="text-surface-800 text-xs font-mono text-center mt-8">
          No account?{" "}
          <Link href="/register" className="text-terminal-400 hover:text-terminal-300 transition-colors">Register</Link>
        </p>
      </div>
    </div>
  );
}
