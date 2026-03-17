"use client";

import { useEffect, useState } from "react";
import ModelCard from "@/components/ModelCard";
import { listAllModels, deployModel, getMe } from "@/lib/api";
import { getToken } from "@/lib/auth";

interface Model {
  id: string;
  slug: string;
  display_name: string;
  hf_repo: string;
  params_b: number;
  quantization: string;
  gpu_type: string;
  gpu_count: number;
  status: string;
  cost_per_1m_input: number;
  cost_per_1m_output: number;
  description: string | null;
  hf_downloads: number | null;
  hf_likes: number | null;
}

const ALL_STATUSES = ["all", "active", "pending", "deploying", "inactive"] as const;

const statusStyle: Record<string, string> = {
  all: "text-neutral-100 border-neutral-100",
  active: "text-terminal-400 border-terminal-400",
  pending: "text-yellow-400 border-yellow-400",
  deploying: "text-blue-400 border-blue-400",
  inactive: "text-surface-700 border-surface-700",
};

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [deployingId, setDeployingId] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (token) {
      getMe(token).then((u) => setIsAdmin(u.is_admin)).catch(() => {});
      listAllModels(token)
        .then(setModels)
        .catch(() => setModels([]))
        .finally(() => setLoading(false));
    } else {
      fetch(`/api/v1/models`)
        .then((r) => r.json())
        .then((data) => {
          setModels(
            data.data?.map((m: any) => ({
              id: m.id,
              slug: m.id,
              display_name: m.id,
              params_b: 0,
              quantization: "",
              gpu_type: "",
              gpu_count: 1,
              status: "active",
              cost_per_1m_input: 0,
              cost_per_1m_output: 0,
              description: null,
              hf_repo: "",
              hf_downloads: null,
              hf_likes: null,
            })) || []
          );
        })
        .catch(() => setModels([]))
        .finally(() => setLoading(false));
    }
  }, []);

  const handleDeploy = async (modelId: string) => {
    const token = getToken();
    if (!token) return;
    setDeployingId(modelId);
    try {
      await deployModel(token, modelId);
      setModels((prev) => prev.map((m) => m.id === modelId ? { ...m, status: "deploying" } : m));
    } catch (e: any) {
      alert(e.message || "Deploy failed");
    } finally {
      setDeployingId(null);
    }
  };

  // Non-admin users only see active models
  const visibleModels = isAdmin ? models : models.filter((m) => m.status === "active");

  const filtered = visibleModels.filter((m) => {
    const matchesText =
      m.display_name.toLowerCase().includes(filter.toLowerCase()) ||
      m.slug.toLowerCase().includes(filter.toLowerCase());
    const matchesStatus = statusFilter === "all" || m.status === statusFilter;
    return matchesText && matchesStatus;
  });

  // Count models per status (for filter badges)
  const statusCounts = visibleModels.reduce<Record<string, number>>((acc, m) => {
    acc[m.status] = (acc[m.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="max-w-7xl mx-auto px-6 py-16">
      <div className="mb-10">
        <p className="section-label mb-4">// Available Models</p>
        <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-2">
          Model Catalog<span className="text-terminal-500 animate-blink">_</span>
        </h1>
        <p className="text-sm font-mono text-surface-800">
          Browse available uncensored and abliterated LLM models
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-4 mb-8">
        <div className="flex-1">
          <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2 block">Search</label>
          <input
            type="text"
            placeholder="Filter models..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="input-field w-full max-w-md"
          />
        </div>

        {isAdmin && (
          <div>
            <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2 block">Status</label>
            <div className="flex gap-1">
              {ALL_STATUSES.map((s) => {
                const count = s === "all" ? visibleModels.length : (statusCounts[s] || 0);
                const isActive = statusFilter === s;
                const style = statusStyle[s] || statusStyle.inactive;
                return (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={`text-[10px] font-mono uppercase tracking-wider px-2.5 py-1.5 border transition-colors ${
                      isActive
                        ? `${style} bg-surface-200`
                        : "text-surface-700 border-surface-400 hover:border-surface-600"
                    }`}
                  >
                    {s} ({count})
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {loading ? (
        <p className="text-surface-800 font-mono text-sm">Loading models...</p>
      ) : filtered.length === 0 ? (
        <div className="border border-surface-400 bg-surface-100 p-12 text-center">
          <p className="text-surface-800 font-mono text-sm">No models found. Check back soon.</p>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered.map((m) => (
            <ModelCard
              key={m.id}
              id={m.id}
              slug={m.slug}
              displayName={m.display_name}
              paramsB={m.params_b}
              quantization={m.quantization}
              gpuType={m.gpu_type}
              gpuCount={m.gpu_count}
              status={m.status}
              costInput={m.cost_per_1m_input}
              costOutput={m.cost_per_1m_output}
              description={m.description}
              hfRepo={m.hf_repo}
              hfDownloads={m.hf_downloads}
              hfLikes={m.hf_likes}
              isAdmin={isAdmin}
              onDeploy={handleDeploy}
              deploying={deployingId === m.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
