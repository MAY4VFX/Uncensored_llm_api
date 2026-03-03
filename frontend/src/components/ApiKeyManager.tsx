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
      <p className="section-label mb-6">// API keys</p>

      {error && <p className="text-red-500 font-mono text-xs mb-4">{error}</p>}

      {newRawKey && (
        <div className="border border-terminal-700 bg-terminal-950/30 p-4 mb-6">
          <p className="text-terminal-400 text-xs font-mono mb-2 uppercase tracking-widest">
            New key generated — copy now
          </p>
          <code className="text-terminal-300 text-xs font-mono break-all bg-surface-0 p-3 block border border-surface-400">
            {newRawKey}
          </code>
          <button
            onClick={() => setNewRawKey(null)}
            className="mt-3 text-xs font-mono text-surface-800 hover:text-neutral-300 uppercase tracking-widest transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="flex gap-px mb-8">
        <input
          type="text"
          placeholder="Key name (optional)"
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          className="input-field flex-1"
        />
        <button
          onClick={handleCreate}
          disabled={loading}
          className="btn-primary disabled:opacity-50"
        >
          Generate
        </button>
      </div>

      <div className="border border-surface-400 divide-y divide-surface-300">
        {keys.map((k) => (
          <div
            key={k.id}
            className="flex items-center justify-between p-4 hover:bg-surface-100 transition-colors"
          >
            <div>
              <p className="text-neutral-200 text-sm font-mono">{k.name}</p>
              <p className="text-surface-800 text-xs font-mono mt-1">
                {k.key_prefix}...{" "}
                <span className={k.is_active ? "text-terminal-500" : "text-red-500"}>
                  [{k.is_active ? "ACTIVE" : "REVOKED"}]
                </span>
              </p>
            </div>
            {k.is_active && (
              <button
                onClick={() => handleRevoke(k.id)}
                className="text-xs font-mono text-surface-800 hover:text-red-500 uppercase tracking-widest transition-colors"
              >
                Revoke
              </button>
            )}
          </div>
        ))}
        {keys.length === 0 && (
          <p className="text-surface-700 text-xs font-mono p-6 text-center">
            No API keys generated yet.
          </p>
        )}
      </div>
    </div>
  );
}
