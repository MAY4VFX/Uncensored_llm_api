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

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [filter, setFilter] = useState("");
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

  const filtered = models.filter(
    (m) =>
      m.display_name.toLowerCase().includes(filter.toLowerCase()) ||
      m.slug.toLowerCase().includes(filter.toLowerCase())
  );

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

      <div className="mb-8">
        <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2 block">Search</label>
        <input
          type="text"
          placeholder="Filter models..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="input-field w-full max-w-md"
        />
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
