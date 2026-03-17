const API_URL = "/api";

interface FetchOptions extends RequestInit {
  token?: string;
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

// Auth
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

// API Keys
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

// Models
export const listModels = () =>
  apiFetch<{ data: Array<{ id: string; object: string; created: number; owned_by: string }> }>("/v1/models");

// Usage
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

// Admin
export const listAllModels = (token: string) =>
  apiFetch<
    Array<{
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
    }>
  >("/admin/models", { token });

export const addModelFromHf = (token: string, hfRepo: string) =>
  apiFetch<any>("/admin/models/add-from-hf", {
    method: "POST",
    token,
    body: { hf_repo: hfRepo },
  });

export const deployModel = (token: string, modelId: string) =>
  apiFetch<{ detail: string; endpoint_id: string }>(`/admin/models/${modelId}/deploy`, {
    method: "POST",
    token,
  });

export const terminateModel = (token: string, modelSlug: string) =>
  apiFetch<{ status: string; message: string }>(`/v1/models/${modelSlug}/terminate`, {
    method: "POST",
    token,
  });

// Keep Warm
export const getKeepWarm = (token: string, modelSlug: string) =>
  apiFetch<{ is_active: boolean; price_per_hour: number; activated_at: string | null; warm_workers: number }>(
    `/v1/models/${modelSlug}/keep-warm`,
    { token }
  );

export const enableKeepWarm = (token: string, modelSlug: string) =>
  apiFetch<{ status: string; price_per_hour: number; warm_workers: number }>(`/v1/models/${modelSlug}/keep-warm`, {
    method: "POST",
    token,
  });

export const disableKeepWarm = (token: string, modelSlug: string) =>
  apiFetch<{ status: string; warm_workers: number }>(`/v1/models/${modelSlug}/keep-warm`, {
    method: "DELETE",
    token,
  });
