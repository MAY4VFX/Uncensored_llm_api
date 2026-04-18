const API_URL = "/api";

interface FetchOptions extends RequestInit {
  token?: string;
}

export interface ProviderCapabilities {
  supports_vllm: boolean;
  supports_gguf: boolean;
  supports_keep_warm: boolean;
  supports_explicit_warm: boolean;
  supports_terminate: boolean;
  supports_queue_status: boolean;
  supports_multigpu: boolean;
}

export interface ProviderOption {
  id: string;
  label: string;
  capabilities: ProviderCapabilities;
}

export interface ProviderSettings {
  default_provider: string;
  modal_default_image: string | null;
  runpod_default_image: string | null;
  provider_flags: Record<string, unknown> | null;
  supported_providers: string[];
}

export interface AdminModel {
  id: string;
  slug: string;
  display_name: string;
  hf_repo: string;
  params_b: number;
  quantization: string;
  gpu_type: string;
  gpu_count: number;
  status: string;
  provider_status: string | null;
  provider_override: string | null;
  effective_provider: string;
  provider_config: Record<string, unknown> | null;
  deployment_ref: string | null;
  runpod_endpoint_id: string | null;
  cost_per_1m_input: number;
  cost_per_1m_output: number;
  description: string | null;
  system_prompt?: string | null;
  hf_downloads: number | null;
  hf_likes: number | null;
  capabilities: ProviderCapabilities;
  created_at: string;
}

export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { token, headers: customHeaders, ...rest } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((customHeaders as Record<string, string>) || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, { headers, ...rest });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }

  return res.json();
}

export const register = (email: string, password: string) =>
  apiFetch<{ access_token: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const login = (email: string, password: string) =>
  apiFetch<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const getMe = (token: string) =>
  apiFetch<{
    id: string;
    email: string;
    credits: number;
    tier: string;
    is_admin: boolean;
  }>("/auth/me", { token });

export const createApiKey = (token: string, name: string) =>
  apiFetch<{ id: string; raw_key: string; key_prefix: string; name: string }>("/api-keys", {
    method: "POST",
    token,
    body: JSON.stringify({ name }),
  });

export const listApiKeys = (token: string) =>
  apiFetch<Array<{ id: string; key_prefix: string; name: string; is_active: boolean; created_at: string }>>(
    "/api-keys",
    { token }
  );

export const revokeApiKey = (token: string, keyId: string) =>
  apiFetch<{ detail: string }>(`/api-keys/${keyId}`, { method: "DELETE", token });

export const listModels = () =>
  apiFetch<{ data: Array<{ id: string; object: string; created: number; owned_by: string }> }>("/v1/models");

export const getUsage = (token: string) =>
  apiFetch<{
    total_tokens_in: number;
    total_tokens_out: number;
    total_gpu_seconds: number;
    total_cost: number;
    credits_remaining: number;
    recent_usage: Array<{
      model_slug: string;
      tokens_in: number;
      tokens_out: number;
      gpu_seconds: number;
      cost: number;
      created_at: string;
    }>;
  }>("/usage/me", { token });

export const listAllModels = (token: string) => apiFetch<AdminModel[]>("/admin/models", { token });

export const getProviderSettings = (token: string) =>
  apiFetch<ProviderSettings>("/admin/settings/providers", { token });

export const updateProviderSettings = (
  token: string,
  payload: Partial<Pick<ProviderSettings, "default_provider" | "modal_default_image" | "runpod_default_image" | "provider_flags">>
) =>
  apiFetch<ProviderSettings>("/admin/settings/providers", {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });

export const listProviders = (token: string) =>
  apiFetch<{ default_provider: string; providers: ProviderOption[] }>("/admin/providers", { token });

export const backfillRunpodOverrides = (token: string) =>
  apiFetch<{ updated: number; detail: string }>("/admin/models/backfill-runpod-overrides", {
    method: "POST",
    token,
  });

export const addModelFromHf = (
  token: string,
  hfRepo: string,
  providerOverride?: string | null
) =>
  apiFetch<AdminModel>("/admin/models/add-from-hf", {
    method: "POST",
    token,
    body: JSON.stringify({ hf_repo: hfRepo, provider_override: providerOverride ?? null }),
  });

export const updateModel = (
  token: string,
  modelId: string,
  payload: Partial<Pick<AdminModel, "provider_override" | "description" | "display_name" | "system_prompt">> & {
    provider_config?: Record<string, unknown> | null;
  }
) =>
  apiFetch<AdminModel>(`/admin/models/${modelId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });

export const deployModel = (token: string, modelId: string) =>
  apiFetch<{ detail: string; provider: string; endpoint_id?: string | null; deployment_ref?: string | null }>(
    `/admin/models/${modelId}/deploy`,
    {
      method: "POST",
      token,
    }
  );

export const setModelStatus = (
  token: string,
  modelId: string,
  status: "active" | "inactive" | "pending" | "deploying"
) =>
  apiFetch<{ detail: string; provider: string; endpoint_id?: string | null; deployment_ref?: string | null }>(
    `/admin/models/${modelId}/status`,
    {
      method: "POST",
      token,
      body: JSON.stringify({ status }),
    }
  );

export const terminateModel = (token: string, modelSlug: string) =>
  apiFetch<{ status: string; message: string; provider: string }>(`/v1/models/${modelSlug}/terminate`, {
    method: "POST",
    token,
  });

export const getKeepWarm = (token: string, modelSlug: string) =>
  apiFetch<{
    is_active: boolean;
    price_per_hour: number;
    activated_at: string | null;
    warm_workers: number;
    provider: string;
    supported: boolean;
    message: string | null;
  }>(`/v1/models/${modelSlug}/keep-warm`, { token });

export const enableKeepWarm = (token: string, modelSlug: string) =>
  apiFetch<{
    status: string;
    price_per_hour: number;
    warm_workers: number;
    provider: string;
    supported: boolean;
    message: string | null;
  }>(`/v1/models/${modelSlug}/keep-warm`, {
    method: "POST",
    token,
  });

export const disableKeepWarm = (token: string, modelSlug: string) =>
  apiFetch<{
    status: string;
    warm_workers: number;
    provider: string;
    supported: boolean;
    message: string | null;
  }>(`/v1/models/${modelSlug}/keep-warm`, {
    method: "DELETE",
    token,
  });
