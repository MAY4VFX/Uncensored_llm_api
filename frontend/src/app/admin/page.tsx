"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { deployModel, getMe, listAllModels } from "@/lib/api";
import { getToken, isAuthenticated } from "@/lib/auth";

interface Model {
  id: string;
  slug: string;
  display_name: string;
  hf_repo: string;
  params_b: number;
  quantization: string;
  gpu_type: string;
  status: string;
  hf_downloads?: number;
  hf_likes?: number;
}

const statusDot: Record<string, string> = {
  active: "bg-terminal-500",
  pending: "bg-yellow-400",
  deploying: "bg-blue-400",
  inactive: "bg-surface-600",
};

const statusText: Record<string, string> = {
  active: "text-terminal-400",
  pending: "text-yellow-400",
  deploying: "text-blue-400",
  inactive: "text-surface-600",
};

export default function AdminPage() {
  const router = useRouter();
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [deploying, setDeploying] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
      return;
    }
    const token = getToken()!;
    getMe(token).then((user) => {
      if (!user.is_admin) {
        router.push("/dashboard");
        return;
      }
      loadModels();
    });
  }, [router]);

  const loadModels = async () => {
    const token = getToken()!;
    try {
      const data = await listAllModels(token);
      setModels(data as Model[]);
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleDeploy = async (modelId: string) => {
    const token = getToken()!;
    setDeploying(modelId);
    try {
      await deployModel(token, modelId);
      await loadModels();
    } catch (e: any) {
      setError(e.message);
    }
    setDeploying(null);
  };

  if (loading) return <div className="text-surface-800 font-mono text-sm p-8">Loading...</div>;

  const pending = models.filter((m) => m.status === "pending");
  const active = models.filter((m) => m.status === "active");
  const other = models.filter((m) => !["pending", "active"].includes(m.status));

  return (
    <div className="max-w-7xl mx-auto px-6 py-16">
      <p className="section-label mb-4">// System Administration</p>
      <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-8">
        Admin Panel<span className="text-terminal-500 animate-blink">_</span>
      </h1>

      {error && (
        <div className="border border-red-900 bg-red-950/30 text-red-400 text-xs font-mono p-3 mb-6">
          {error}
        </div>
      )}

      {/* Pending Models */}
      {pending.length > 0 && (
        <section className="mb-10">
          <p className="section-label mb-4">
            // Pending Approval ({pending.length})
          </p>
          <div className="space-y-3">
            {pending.map((m) => (
              <div key={m.id} className="border border-surface-400 bg-surface-100 p-4 flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h3 className="text-neutral-100 font-mono font-bold">{m.display_name}</h3>
                    <span className="flex items-center gap-1.5">
                      <span className={`inline-block w-1.5 h-1.5 ${statusDot[m.status] || "bg-surface-600"}`}></span>
                      <span className={`text-xs font-mono uppercase tracking-[0.2em] ${statusText[m.status] || "text-surface-600"}`}>
                        {m.status}
                      </span>
                    </span>
                  </div>
                  <p className="text-surface-800 text-sm font-mono mt-1">
                    {m.hf_repo} &middot; {m.params_b}B &middot; {m.quantization} &middot; {m.gpu_type}
                  </p>
                </div>
                <button
                  onClick={() => handleDeploy(m.id)}
                  disabled={deploying === m.id}
                  className="btn-primary text-sm disabled:opacity-50"
                >
                  {deploying === m.id ? "Deploying..." : "Deploy"}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Active Models */}
      <section className="mb-10">
        <p className="section-label mb-4">
          // Active Models ({active.length})
        </p>
        {active.length === 0 ? (
          <div className="border border-surface-400 bg-surface-100 p-8 text-center">
            <p className="text-surface-800 font-mono text-sm">No active models yet.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {active.map((m) => (
              <div key={m.id} className="border border-surface-400 bg-surface-100 p-4 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="text-neutral-100 font-mono font-bold">{m.display_name}</h3>
                    <span className="flex items-center gap-1.5">
                      <span className={`inline-block w-1.5 h-1.5 ${statusDot[m.status] || "bg-surface-600"}`}></span>
                      <span className={`text-xs font-mono uppercase tracking-[0.2em] ${statusText[m.status] || "text-surface-600"}`}>
                        {m.status}
                      </span>
                    </span>
                  </div>
                  <p className="text-surface-800 text-sm font-mono mt-1">
                    {m.hf_repo} &middot; {m.params_b}B &middot; {m.quantization} &middot; {m.gpu_type}
                  </p>
                </div>
                <code className="text-surface-600 text-xs font-mono">{m.slug}</code>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Other */}
      {other.length > 0 && (
        <section>
          <p className="section-label mb-4">
            // Other ({other.length})
          </p>
          <div className="space-y-3">
            {other.map((m) => (
              <div key={m.id} className="border border-surface-400 bg-surface-100 p-4 flex items-center justify-between opacity-60">
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="text-neutral-100 font-mono font-bold">{m.display_name}</h3>
                    <span className="flex items-center gap-1.5">
                      <span className={`inline-block w-1.5 h-1.5 ${statusDot[m.status] || "bg-surface-600"}`}></span>
                      <span className={`text-xs font-mono uppercase tracking-[0.2em] ${statusText[m.status] || "text-surface-600"}`}>
                        {m.status}
                      </span>
                    </span>
                  </div>
                  <p className="text-surface-800 text-sm font-mono mt-1">
                    {m.hf_repo} &middot; {m.status}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
