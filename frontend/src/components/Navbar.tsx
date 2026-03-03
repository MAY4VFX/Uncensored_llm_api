"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { clearToken, getToken } from "@/lib/auth";
import { getMe } from "@/lib/api";

export default function Navbar() {
  const router = useRouter();
  const [user, setUser] = useState<{ email: string; is_admin: boolean } | null>(null);

  useEffect(() => {
    const token = getToken();
    if (token) {
      getMe(token)
        .then(setUser)
        .catch(() => clearToken());
    }
  }, []);

  const handleLogout = () => {
    clearToken();
    setUser(null);
    router.push("/");
  };

  const navLink = "text-surface-900 hover:text-terminal-400 text-xs font-mono uppercase tracking-widest transition-colors";

  return (
    <nav className="bg-surface-0/90 backdrop-blur-sm border-b border-surface-300 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-10">
            <Link href="/" className="font-mono text-sm font-bold text-terminal-400 tracking-wider">
              UNCHAINED<span className="text-surface-700">_</span>API
            </Link>
            <div className="hidden md:flex gap-8">
              <Link href="/models" className={navLink}>Models</Link>
              <Link href="/playground" className={navLink}>Playground</Link>
              <Link href="/docs" className={navLink}>Docs</Link>
              {user && <Link href="/dashboard" className={navLink}>Dashboard</Link>}
              {user?.is_admin && (
                <Link href="/admin" className="text-terminal-600 hover:text-terminal-400 text-xs font-mono uppercase tracking-widest transition-colors">
                  Admin
                </Link>
              )}
            </div>
          </div>

          <div className="flex items-center gap-6">
            {user ? (
              <>
                <span className="text-surface-800 text-xs font-mono">{user.email}</span>
                <button onClick={handleLogout} className={navLink}>
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link href="/login" className={navLink}>Login</Link>
                <Link
                  href="/register"
                  className="bg-terminal-500 hover:bg-terminal-400 text-black px-4 py-1.5 text-xs font-mono uppercase tracking-widest transition-colors"
                >
                  Sign Up
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
