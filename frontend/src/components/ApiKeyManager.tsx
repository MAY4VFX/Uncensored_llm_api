"use client";

import { useEffect, useState } from "react";
import { createApiKey, listApiKeys, revokeApiKey } from "@/lib/api";
import { getToken } from "@/lib/auth";

interface ApiKeyItem {
  id: string;
  key_prefix: string;
  name: string;
  is_active: boolean;
  created_at: string;
}

export default function ApiKeyManager() {
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [newRawKey, setNewRawKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const token = getToken();

  const loadKeys = async () => {
    if (!token) return;
    try {
      const data = await listApiKeys(token);
      setKeys(data);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    loadKeys();
  }, []);

  const handleCreate = async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const result = await createApiKey(token, newKeyName || "Default");
      setNewRawKey(result.raw_key);
      setNewKeyName("");
      await loadKeys();
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleRevoke = async (keyId: string) => {
    if (!token) return;
    try {
      await revokeApiKey(token, keyId);
      await loadKeys();
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-4">API Keys</h2>

      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

      {newRawKey && (
        <div className="bg-green-900/30 border border-green-700 rounded-lg p-4 mb-4">
          <p className="text-green-400 text-sm mb-2">
            Your new API key (copy it now, it won&apos;t be shown again):
          </p>
          <code className="text-green-300 text-sm break-all bg-gray-900 p-2 rounded block">
            {newRawKey}
          </code>
          <button
            onClick={() => setNewRawKey(null)}
            className="mt-2 text-sm text-gray-400 hover:text-white"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="flex gap-3 mb-6">
        <input
          type="text"
          placeholder="Key name (optional)"
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white text-sm flex-1"
        />
        <button
          onClick={handleCreate}
          disabled={loading}
          className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm disabled:opacity-50"
        >
          Create Key
        </button>
      </div>

      <div className="space-y-3">
        {keys.map((k) => (
          <div
            key={k.id}
            className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-lg p-4"
          >
            <div>
              <p className="text-white text-sm font-medium">{k.name}</p>
              <p className="text-gray-400 text-xs mt-1">
                {k.key_prefix}...{" "}
                <span className={k.is_active ? "text-green-400" : "text-red-400"}>
                  {k.is_active ? "Active" : "Revoked"}
                </span>
              </p>
            </div>
            {k.is_active && (
              <button
                onClick={() => handleRevoke(k.id)}
                className="text-red-400 hover:text-red-300 text-sm"
              >
                Revoke
              </button>
            )}
          </div>
        ))}
        {keys.length === 0 && (
          <p className="text-gray-500 text-sm">No API keys yet. Create one above.</p>
        )}
      </div>
    </div>
  );
}
