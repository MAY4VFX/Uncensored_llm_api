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

  return (
    <nav className="bg-gray-950/80 backdrop-blur-md border-b border-gray-800/50 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <Link href="/" className="text-xl font-bold gradient-text">
              UnchainedAPI
            </Link>
            <div className="hidden md:flex gap-6">
              <Link href="/models" className="text-gray-300 hover:text-white text-sm">
                Models
              </Link>
              <Link href="/docs" className="text-gray-300 hover:text-white text-sm">
                Docs
              </Link>
              {user && (
                <Link href="/dashboard" className="text-gray-300 hover:text-white text-sm">
                  Dashboard
                </Link>
              )}
              {user?.is_admin && (
                <Link href="/admin" className="text-yellow-400 hover:text-yellow-300 text-sm">
                  Admin
                </Link>
              )}
            </div>
          </div>

          <div className="flex items-center gap-4">
            {user ? (
              <>
                <span className="text-gray-400 text-sm">{user.email}</span>
                <button
                  onClick={handleLogout}
                  className="text-gray-300 hover:text-white text-sm"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="text-gray-300 hover:text-white text-sm"
                >
                  Login
                </Link>
                <Link
                  href="/register"
                  className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm"
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
