"use client";

import { useEffect, useState } from "react";
import ModelCard from "@/components/ModelCard";
import {
  addModelFromHf,
  AdminModel,
  backfillRunpodOverrides,
  deployModel,
  getMe,
  getProviderSettings,
  listAllModels,
  updateProviderSettings,
  listProviders,
  ProviderOption,
  ProviderSettings,
  setModelStatus,
  updateModel,
} from "@/lib/api";
import { getToken } from "@/lib/auth";

const ALL_STATUSES = ["all", "active", "pending", "deploying", "inactive"] as const;
const SIZE_BUCKETS = ["all", "lt10", "10to30", "30to70", "70plus"] as const;
const QUANT_FILTERS = ["FP16", "Q8", "Q4", "GGUF"] as const;
const TAG_FILTERS = ["Uncensored", "Qwen", "Gemma", "Reasoning", "Abliterated", "MoE", "Heretic", "GPT-OSS"] as const;
const SORT_OPTIONS = ["newest", "downloads", "likes"] as const;

type SizeBucket = (typeof SIZE_BUCKETS)[number];
type QuantFilter = (typeof QUANT_FILTERS)[number];
type TagFilter = (typeof TAG_FILTERS)[number];
type SortOption = (typeof SORT_OPTIONS)[number];

const statusStyle: Record<string, string> = {
  all: "text-neutral-100 border-neutral-100",
  active: "text-terminal-400 border-terminal-400",
  pending: "text-yellow-400 border-yellow-400",
  deploying: "text-blue-400 border-blue-400",
  inactive: "text-surface-700 border-surface-700",
};

const sizeLabels: Record<SizeBucket, string> = {
  all: "All sizes",
  lt10: "<10B",
  "10to30": "10–30B",
  "30to70": "30–70B",
  "70plus": "70B+",
};

const sortLabels: Record<SortOption, string> = {
  newest: "Newest added",
  downloads: "Most downloads",
  likes: "Most likes",
};

function normalizeModelText(model: AdminModel): string {
  return [model.slug, model.hf_repo, model.display_name, model.description || "", model.effective_provider || ""].join(" ").toLowerCase();
}

function getDerivedTags(model: AdminModel): Set<TagFilter> {
  const text = normalizeModelText(model);
  const tags = new Set<TagFilter>();

  if (/(uncensored|unaligned|unfiltered|derestricted|amoral)/i.test(text)) tags.add("Uncensored");
  if (/(qwen|qwopus|omnicoder)/i.test(text)) tags.add("Qwen");
  if (/(gemma|supergemma)/i.test(text)) tags.add("Gemma");
  if (/(reasoning|thinking|distill|distilled|\br1\b)/i.test(text)) tags.add("Reasoning");
  if (/(abliterated|lorablated)/i.test(text)) tags.add("Abliterated");
  if (/(\bmoe\b|a3b|a4b|a12b|a35b|8x|96e|e2b|e4b)/i.test(text)) tags.add("MoE");
  if (/heretic/i.test(text)) tags.add("Heretic");
  if (/(gpt-oss|gpt_oss)/i.test(text)) tags.add("GPT-OSS");

  return tags;
}

function getSizeBucket(paramsB: number): SizeBucket {
  if (paramsB < 10) return "lt10";
  if (paramsB < 30) return "10to30";
  if (paramsB < 70) return "30to70";
  return "70plus";
}

function matchesQuantFilter(model: AdminModel, selectedQuant: QuantFilter | null): boolean {
  if (!selectedQuant) return true;

  const text = normalizeModelText(model);
  const quant = (model.quantization || "").toUpperCase();

  if (selectedQuant === "GGUF") {
    return /gguf/i.test(text) || quant === "GGUF";
  }

  return quant === selectedQuant;
}

function matchesTagFilter(model: AdminModel, selectedTags: TagFilter[]): boolean {
  if (selectedTags.length === 0) return true;
  const derivedTags = getDerivedTags(model);
  return selectedTags.every((tag) => derivedTags.has(tag));
}

function chipClass(isActive: boolean, activeStyle: string) {
  return `text-[10px] font-mono uppercase tracking-wider px-2.5 py-1.5 border transition-colors ${
    isActive ? `${activeStyle} bg-surface-200` : "text-surface-700 border-surface-400 hover:border-surface-600"
  }`;
}

export default function ModelsPage() {
  const [models, setModels] = useState<AdminModel[]>([]);
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [providerSettings, setProviderSettings] = useState<ProviderSettings | null>(null);
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sizeFilter, setSizeFilter] = useState<SizeBucket>("all");
  const [quantFilter, setQuantFilter] = useState<QuantFilter | null>(null);
  const [tagFilters, setTagFilters] = useState<TagFilter[]>([]);
  const [sortBy, setSortBy] = useState<SortOption>("newest");
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [deployingId, setDeployingId] = useState<string | null>(null);
  const [undeployingId, setUndeployingId] = useState<string | null>(null);
  const [hfInput, setHfInput] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");
  const [savingDefaultProvider, setSavingDefaultProvider] = useState(false);
  const [savingOverrideId, setSavingOverrideId] = useState<string | null>(null);
  const [pinningExisting, setPinningExisting] = useState(false);

  const refreshAdminData = async (token: string) => {
    const [modelsData, settingsData, providersData] = await Promise.all([
      listAllModels(token),
      getProviderSettings(token),
      listProviders(token),
    ]);
    setModels(modelsData);
    setProviderSettings(settingsData);
    setProviders(providersData.providers);
  };

  useEffect(() => {
    const token = getToken();
    if (token) {
      getMe(token)
        .then(async (u) => {
          setIsAdmin(u.is_admin);
          if (u.is_admin) {
            await refreshAdminData(token);
          } else {
            const modelsData = await listAllModels(token).catch(() => [] as AdminModel[]);
            setModels(modelsData.filter((model) => model.status === "active"));
          }
        })
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
              hf_repo: "",
              params_b: 0,
              quantization: "",
              gpu_type: "",
              gpu_count: 1,
              status: "active",
              provider_status: "active",
              provider_override: null,
              effective_provider: "runpod",
              provider_config: null,
              deployment_ref: null,
              runpod_endpoint_id: null,
              cost_per_1m_input: 0,
              cost_per_1m_output: 0,
              description: null,
              system_prompt: null,
              hf_downloads: null,
              hf_likes: null,
              capabilities: {
                supports_vllm: true,
                supports_gguf: true,
                supports_keep_warm: false,
                supports_explicit_warm: false,
                supports_terminate: false,
                supports_queue_status: false,
                supports_multigpu: false,
              },
              created_at: m.created ? new Date(m.created * 1000).toISOString() : new Date().toISOString(),
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
      await refreshAdminData(token);
    } catch (e: any) {
      alert(e.message || "Deploy failed");
    } finally {
      setDeployingId(null);
    }
  };

  const handleUndeploy = async (modelId: string) => {
    const token = getToken();
    if (!token) return;
    setUndeployingId(modelId);
    try {
      await setModelStatus(token, modelId, "inactive");
      await refreshAdminData(token);
    } catch (e: any) {
      alert(e.message || "Undeploy failed");
    } finally {
      setUndeployingId(null);
    }
  };

  const handleAddFromHf = async () => {
    const token = getToken();
    if (!token || !hfInput.trim()) return;
    setAdding(true);
    setAddError("");
    try {
      const newModel = await addModelFromHf(token, hfInput.trim(), null);
      setModels((prev) => [newModel, ...prev]);
      setHfInput("");
    } catch (e: any) {
      setAddError(e.message || "Failed to add model");
    } finally {
      setAdding(false);
    }
  };

  const handleDefaultProviderChange = async (provider: string) => {
    const token = getToken();
    if (!token) return;
    setSavingDefaultProvider(true);
    try {
      const next = await updateProviderSettings(token, { default_provider: provider });
      setProviderSettings(next);
      await refreshAdminData(token);
    } catch (e: any) {
      alert(e.message || "Failed to update default provider");
    } finally {
      setSavingDefaultProvider(false);
    }
  };

  const handleProviderOverrideChange = async (modelId: string, value: string) => {
    const token = getToken();
    if (!token) return;
    setSavingOverrideId(modelId);
    try {
      await updateModel(token, modelId, { provider_override: value === "inherit" ? null : value });
      await refreshAdminData(token);
    } catch (e: any) {
      alert(e.message || "Failed to update provider override");
    } finally {
      setSavingOverrideId(null);
    }
  };

  const handleBackfillRunpod = async () => {
    const token = getToken();
    if (!token) return;
    setPinningExisting(true);
    try {
      const result = await backfillRunpodOverrides(token);
      alert(result.detail);
      await refreshAdminData(token);
    } catch (e: any) {
      alert(e.message || "Failed to pin existing models");
    } finally {
      setPinningExisting(false);
    }
  };

  const toggleQuantFilter = (quant: QuantFilter) => {
    setQuantFilter((prev) => (prev === quant ? null : quant));
  };

  const toggleTagFilter = (tag: TagFilter) => {
    setTagFilters((prev) => (prev.includes(tag) ? prev.filter((value) => value !== tag) : [...prev, tag]));
  };

  const clearFilters = () => {
    setStatusFilter("all");
    setSizeFilter("all");
    setQuantFilter(null);
    setTagFilters([]);
    setSortBy("newest");
  };

  const visibleModels = isAdmin ? models : models.filter((m) => m.status === "active");

  const filtered = visibleModels.filter((m) => {
    const query = filter.toLowerCase();
    const matchesText =
      m.display_name.toLowerCase().includes(query) ||
      m.slug.toLowerCase().includes(query) ||
      m.hf_repo.toLowerCase().includes(query) ||
      (m.description || "").toLowerCase().includes(query) ||
      (m.effective_provider || "").toLowerCase().includes(query);

    const matchesStatus = statusFilter === "all" || m.status === statusFilter;
    const matchesSize = sizeFilter === "all" || getSizeBucket(m.params_b) === sizeFilter;
    const matchesQuant = matchesQuantFilter(m, quantFilter);
    const matchesTags = matchesTagFilter(m, tagFilters);

    return matchesText && matchesStatus && matchesSize && matchesQuant && matchesTags;
  });

  const sortedModels = [...filtered].sort((a, b) => {
    if (sortBy === "downloads") {
      return (b.hf_downloads || 0) - (a.hf_downloads || 0);
    }
    if (sortBy === "likes") {
      return (b.hf_likes || 0) - (a.hf_likes || 0);
    }

    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
    return bTime - aTime;
  });

  const statusCounts = visibleModels.reduce<Record<string, number>>((acc, m) => {
    acc[m.status] = (acc[m.status] || 0) + 1;
    return acc;
  }, {});

  const activeFilterCount =
    (statusFilter !== "all" ? 1 : 0) +
    (sizeFilter !== "all" ? 1 : 0) +
    (quantFilter ? 1 : 0) +
    tagFilters.length;

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

      {isAdmin && providerSettings && (
        <div className="mb-8 border border-surface-400 bg-surface-100 p-4 space-y-4">
          <div className="flex flex-col lg:flex-row lg:items-end gap-4">
            <div className="flex-1 min-w-[220px]">
              <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2 block">Global default provider</label>
              <select
                value={providerSettings.default_provider}
                onChange={(e) => handleDefaultProviderChange(e.target.value)}
                disabled={savingDefaultProvider}
                className="input-field w-full"
              >
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1 text-xs font-mono text-surface-800 leading-relaxed">
              New models without override inherit <span className="text-neutral-100">{providerSettings.default_provider}</span>.
              Existing models should stay pinned to <span className="text-neutral-100">runpod</span> during migration.
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {providers.map((provider) => (
              <span key={provider.id} className="text-[10px] font-mono uppercase tracking-widest px-2 py-1 border border-surface-400 text-surface-700 bg-surface-50">
                {provider.id} • {provider.capabilities.supports_keep_warm ? "keep-warm" : "no keep-warm"} • {provider.capabilities.supports_gguf ? "gguf" : "no gguf"}
              </span>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-surface-300 pt-3">
            <button
              onClick={handleBackfillRunpod}
              disabled={pinningExisting}
              className="text-[10px] font-mono uppercase tracking-wider px-3 py-1.5 border text-terminal-400 border-terminal-800 bg-terminal-950/40 hover:bg-terminal-900/60 transition-colors disabled:opacity-40"
            >
              {pinningExisting ? "Pinning..." : "Pin existing models to RunPod"}
            </button>
            <span className="text-xs font-mono text-surface-800">
              Use once after migration to preserve the current RunPod baseline while default provider is Modal.
            </span>
          </div>
        </div>
      )}

      <div className="space-y-4 mb-8">
        <div className="flex flex-col sm:flex-row gap-4">
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
              <div className="flex flex-wrap gap-1">
                {ALL_STATUSES.map((s) => {
                  const count = s === "all" ? visibleModels.length : statusCounts[s] || 0;
                  const isActive = statusFilter === s;
                  const style = statusStyle[s] || statusStyle.inactive;
                  return (
                    <button key={s} onClick={() => setStatusFilter(s)} className={chipClass(isActive, style)}>
                      {s} ({count})
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {isAdmin && (
          <div className="flex flex-wrap gap-2 border-t border-surface-300 pt-3">
            {SIZE_BUCKETS.filter((bucket) => bucket !== "all").map((bucket) => {
              const isActive = sizeFilter === bucket;
              return (
                <button
                  key={bucket}
                  onClick={() => setSizeFilter(isActive ? "all" : bucket)}
                  className={chipClass(isActive, "text-terminal-400 border-terminal-400")}
                >
                  {sizeLabels[bucket]}
                </button>
              );
            })}

            {QUANT_FILTERS.map((quant) => {
              const isActive = quantFilter === quant;
              return (
                <button
                  key={quant}
                  onClick={() => toggleQuantFilter(quant)}
                  className={chipClass(isActive, "text-terminal-400 border-terminal-400")}
                >
                  {quant}
                </button>
              );
            })}

            {TAG_FILTERS.map((tag) => {
              const isActive = tagFilters.includes(tag);
              return (
                <button
                  key={tag}
                  onClick={() => toggleTagFilter(tag)}
                  className={chipClass(isActive, "text-terminal-400 border-terminal-400")}
                >
                  {tag}
                </button>
              );
            })}
          </div>
        )}

        {isAdmin && (
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-t border-surface-300 pt-3">
            <div className="flex items-center gap-2">
              <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900">Sort by</label>
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortOption)} className="input-field w-auto min-w-[180px]">
                <option value="newest">Newest added</option>
                <option value="downloads">Most downloads</option>
                <option value="likes">Most likes</option>
              </select>
            </div>

            <button
              onClick={clearFilters}
              disabled={activeFilterCount === 0 && sortBy === "newest"}
              className="text-[10px] font-mono uppercase tracking-wider px-3 py-1.5 border text-surface-700 border-surface-400 hover:border-surface-600 disabled:opacity-40 disabled:hover:border-surface-400 transition-colors self-start"
            >
              Clear chips
            </button>
          </div>
        )}

        <div className="border-t border-surface-300 pt-3">
          <p className="text-xs font-mono text-surface-800">
            {sortedModels.length} models found{isAdmin ? ` • sorted by ${sortLabels[sortBy]}` : ""}
          </p>
        </div>
      </div>

      {isAdmin && (
        <div className="mb-8 border border-surface-400 bg-surface-100 p-4">
          <label className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2 block">Add model from HuggingFace</label>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="org/model-name"
              value={hfInput}
              onChange={(e) => setHfInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddFromHf()}
              className="input-field flex-1"
            />
            <button
              onClick={handleAddFromHf}
              disabled={adding || !hfInput.trim()}
              className="btn-primary text-sm disabled:opacity-50 whitespace-nowrap"
            >
              {adding ? "Adding..." : "Add Model"}
            </button>
          </div>
          <p className="text-[10px] font-mono text-surface-700 mt-2">
            New entries inherit the global default provider unless you set a per-model override afterwards.
          </p>
          {addError && <p className="text-red-400 text-xs font-mono mt-2">{addError}</p>}
        </div>
      )}

      {loading ? (
        <p className="text-surface-800 font-mono text-sm">Loading models...</p>
      ) : sortedModels.length === 0 ? (
        <div className="border border-surface-400 bg-surface-100 p-12 text-center">
          <p className="text-surface-800 font-mono text-sm">No models found. Check back soon.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {isAdmin && (
            <div className="border border-surface-300 bg-surface-100/60 p-4">
              <div className="grid md:grid-cols-[1.4fr_0.9fr_0.9fr_1fr] gap-3 text-[10px] font-mono uppercase tracking-widest text-surface-700">
                <span>Model</span>
                <span>Effective provider</span>
                <span>Override</span>
                <span>Admin control</span>
              </div>
            </div>
          )}

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {sortedModels.map((m) => (
              <div key={m.id} className="space-y-3">
                {isAdmin && providerSettings && (
                  <div className="border border-surface-300 bg-surface-100/60 p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2 text-[10px] font-mono uppercase tracking-widest">
                      <span className="text-surface-800">effective provider</span>
                      <span className="text-neutral-100">{m.effective_provider}</span>
                    </div>
                    <div className="flex items-center justify-between gap-2 text-[10px] font-mono uppercase tracking-widest">
                      <span className="text-surface-800">default</span>
                      <span className="text-surface-700">{providerSettings.default_provider}</span>
                    </div>
                    <div>
                      <label className="text-[10px] font-mono uppercase tracking-widest text-surface-800 mb-1 block">Per-model override</label>
                      <select
                        value={m.provider_override ?? "inherit"}
                        onChange={(e) => handleProviderOverrideChange(m.id, e.target.value)}
                        disabled={savingOverrideId === m.id}
                        className="input-field w-full text-xs"
                      >
                        <option value="inherit">inherit default ({providerSettings.default_provider})</option>
                        {providers.map((provider) => (
                          <option key={provider.id} value={provider.id}>
                            {provider.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="text-[10px] font-mono text-surface-700 leading-relaxed">
                      {m.provider_override
                        ? `Pinned to ${m.provider_override}.`
                        : `No override — inherits ${providerSettings.default_provider}.`}
                    </div>
                    <div className="flex flex-wrap gap-2 text-[10px] font-mono uppercase tracking-widest text-surface-700">
                      <span className="px-2 py-1 border border-surface-400">{m.capabilities.supports_keep_warm ? "keep-warm" : "no keep-warm"}</span>
                      <span className="px-2 py-1 border border-surface-400">{m.capabilities.supports_terminate ? "terminate" : "no terminate"}</span>
                      <span className="px-2 py-1 border border-surface-400">{m.capabilities.supports_gguf ? "gguf" : "no gguf"}</span>
                    </div>
                  </div>
                )}

                <ModelCard
                  id={m.id}
                  slug={m.slug}
                  displayName={m.display_name}
                  paramsB={m.params_b}
                  quantization={m.quantization}
                  gpuType={m.gpu_type}
                  gpuCount={m.gpu_count}
                  status={m.status}
                  providerStatus={m.provider_status}
                  effectiveProvider={m.effective_provider}
                  providerOverride={m.provider_override}
                  deploymentRef={m.deployment_ref}
                  runpodEndpointId={m.runpod_endpoint_id}
                  supportsKeepWarm={m.capabilities.supports_keep_warm}
                  supportsTerminate={m.capabilities.supports_terminate}
                  costInput={m.cost_per_1m_input}
                  costOutput={m.cost_per_1m_output}
                  description={m.description}
                  hfRepo={m.hf_repo}
                  hfDownloads={m.hf_downloads}
                  hfLikes={m.hf_likes}
                  isAdmin={isAdmin}
                  onDeploy={handleDeploy}
                  onUndeploy={handleUndeploy}
                  deploying={deployingId === m.id}
                  undeploying={undeployingId === m.id}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
