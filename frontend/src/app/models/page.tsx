"use client";

import { useEffect, useState } from "react";
import ModelCard from "@/components/ModelCard";
import { listAllModels } from "@/lib/api";
import { getToken } from "@/lib/auth";

interface Model {
  id: string;
  slug: string;
  display_name: string;
  hf_repo: string;
  params_b: number;
  quantization: string;
  gpu_type: string;
  status: string;
  cost_per_1m_input: number;
  cost_per_1m_output: number;
  description: string | null;
}

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Try authenticated endpoint first (shows all models), fallback to public
    const token = getToken();
    if (token) {
      listAllModels(token)
        .then(setModels)
        .catch(() => setModels([]))
        .finally(() => setLoading(false));
    } else {
      // Public endpoint only shows active models via /v1/models
      fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/v1/models`)
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
              status: "active",
              cost_per_1m_input: 0,
              cost_per_1m_output: 0,
              description: null,
              hf_repo: "",
            })) || []
          );
        })
        .catch(() => setModels([]))
        .finally(() => setLoading(false));
    }
  }, []);

  const filtered = models.filter(
    (m) =>
      m.display_name.toLowerCase().includes(filter.toLowerCase()) ||
      m.slug.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="max-w-7xl mx-auto px-4 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Model Catalog</h1>
        <p className="text-gray-400">
          Browse available uncensored and abliterated LLM models
        </p>
      </div>

      <input
        type="text"
        placeholder="Search models..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="input-field w-full max-w-md mb-8"
      />

      {loading ? (
        <div className="text-gray-400">Loading models...</div>
      ) : filtered.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <p className="text-gray-400">No models found. Check back soon!</p>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered.map((m) => (
            <ModelCard
              key={m.id}
              slug={m.slug}
              displayName={m.display_name}
              paramsB={m.params_b}
              quantization={m.quantization}
              gpuType={m.gpu_type}
              status={m.status}
              costInput={m.cost_per_1m_input}
              costOutput={m.cost_per_1m_output}
              description={m.description}
            />
          ))}
        </div>
      )}
    </div>
  );
}
