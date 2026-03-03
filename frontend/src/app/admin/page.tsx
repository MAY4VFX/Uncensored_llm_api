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

const statusColors: Record<string, string> = {
  active: "bg-green-500/20 text-green-400",
  pending: "bg-yellow-500/20 text-yellow-400",
  deploying: "bg-blue-500/20 text-blue-400",
  inactive: "bg-gray-500/20 text-gray-400",
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

  if (loading) return <div className="text-gray-400 p-8">Loading...</div>;

  const pending = models.filter((m) => m.status === "pending");
  const active = models.filter((m) => m.status === "active");
  const other = models.filter((m) => !["pending", "active"].includes(m.status));

  return (
    <div className="max-w-7xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-white mb-8">Admin Panel</h1>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg p-3 mb-6">
          {error}
        </div>
      )}

      {/* Pending Models */}
      {pending.length > 0 && (
        <section className="mb-10">
          <h2 className="text-xl font-semibold text-yellow-400 mb-4">
            Pending Approval ({pending.length})
          </h2>
          <div className="space-y-3">
            {pending.map((m) => (
              <div key={m.id} className="glass-card p-4 flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h3 className="text-white font-medium">{m.display_name}</h3>
                    <span className={`px-2 py-0.5 rounded-full text-xs ${statusColors[m.status]}`}>
                      {m.status}
                    </span>
                  </div>
                  <p className="text-gray-400 text-sm mt-1">
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
        <h2 className="text-xl font-semibold text-green-400 mb-4">
          Active Models ({active.length})
        </h2>
        {active.length === 0 ? (
          <p className="text-gray-500">No active models yet.</p>
        ) : (
          <div className="space-y-3">
            {active.map((m) => (
              <div key={m.id} className="glass-card p-4 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="text-white font-medium">{m.display_name}</h3>
                    <span className={`px-2 py-0.5 rounded-full text-xs ${statusColors[m.status]}`}>
                      {m.status}
                    </span>
                  </div>
                  <p className="text-gray-400 text-sm mt-1">
                    {m.hf_repo} &middot; {m.params_b}B &middot; {m.quantization} &middot; {m.gpu_type}
                  </p>
                </div>
                <code className="text-gray-500 text-xs">{m.slug}</code>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Other */}
      {other.length > 0 && (
        <section>
          <h2 className="text-xl font-semibold text-gray-400 mb-4">
            Other ({other.length})
          </h2>
          <div className="space-y-3">
            {other.map((m) => (
              <div key={m.id} className="glass-card p-4 flex items-center justify-between opacity-60">
                <div>
                  <h3 className="text-white font-medium">{m.display_name}</h3>
                  <p className="text-gray-400 text-sm">{m.hf_repo} &middot; {m.status}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
