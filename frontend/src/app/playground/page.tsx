"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken, isAuthenticated } from "@/lib/auth";
import { getMe } from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface ModelOption {
  id: string;
  name: string;
}

export default function PlaygroundPage() {
  const router = useRouter();
  const [user, setUser] = useState<{ email: string; credits: number } | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState("");

  const API_URL = "/api";

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
      return;
    }
    const token = getToken()!;
    getMe(token).then(setUser).catch(() => router.push("/login"));

    // Load available models
    fetch(`${API_URL}/v1/models`)
      .then((r) => r.json())
      .then((data) => {
        const modelList = data.data?.map((m: any) => ({ id: m.id, name: m.id })) || [];
        setModels(modelList);
        if (modelList.length > 0) setSelectedModel(modelList[0].id);
      })
      .catch(() => {});
  }, [router, API_URL]);

  const handleSend = async () => {
    if (!input.trim() || isStreaming || !selectedModel) return;

    const token = getToken();
    if (!token) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
    };

    const allMessages = [...messages, userMessage];
    setMessages(allMessages);
    setInput("");
    setIsStreaming(true);
    setError("");

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }]);

    try {
      const response = await fetch(`${API_URL}/playground/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          model: selectedModel,
          messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
          stream: true,
          max_tokens: 2048,
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Request failed" }));
        throw new Error(err.detail || `Error ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = line.slice(6);
              if (data === "[DONE]") continue;

              try {
                const parsed = JSON.parse(data);
                const delta = parsed.choices?.[0]?.delta?.content;
                if (delta) {
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId ? { ...m, content: m.content + delta } : m
                    )
                  );
                }
              } catch {
                // Skip malformed SSE chunks
              }
            }
          }
        }
      }

      // Refresh user credits
      getMe(token).then(setUser);
    } catch (err: any) {
      setError(err.message);
      // Remove empty assistant message on error
      setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content));
    }

    setIsStreaming(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => {
    setMessages([]);
    setError("");
  };

  if (!user) return <div className="text-surface-800 font-mono text-sm p-8">Loading...</div>;

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Header bar */}
      <div className="border-b border-surface-300 px-6 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-6">
          <p className="text-xs font-mono uppercase tracking-widest text-surface-900">// Playground</p>

          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="bg-surface-100 border border-surface-400 px-3 py-1.5 text-xs font-mono text-neutral-300 focus:outline-none focus:border-terminal-500/60"
          >
            {models.length === 0 && <option value="">No models available</option>}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-6">
          <span className="text-xs font-mono text-surface-800">
            credits: <span className="text-terminal-400">${user.credits.toFixed(4)}</span>
          </span>
          <button
            onClick={handleClear}
            className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1">
        {messages.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <p className="text-surface-700 font-mono text-sm mb-2">
                Select a model and start chatting.
              </p>
              <p className="text-surface-600 font-mono text-xs">
                Credits will be deducted per request.
              </p>
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className="py-4 border-b border-surface-200">
            <div className="flex items-start gap-4 max-w-4xl">
              <span
                className={`text-[10px] font-mono uppercase tracking-widest mt-1 w-16 shrink-0 ${
                  m.role === "user" ? "text-surface-800" : "text-terminal-500"
                }`}
              >
                {m.role === "user" ? "you" : "model"}
              </span>
              <div className="flex-1 min-w-0">
                <pre className="text-sm text-neutral-300 font-mono whitespace-pre-wrap break-words leading-relaxed">
                  {m.content}
                  {m.role === "assistant" && isStreaming && m.content === "" && (
                    <span className="text-terminal-500 animate-blink">_</span>
                  )}
                  {m.role === "assistant" && isStreaming && m.content !== "" && (
                    <span className="text-terminal-500 animate-blink">|</span>
                  )}
                </pre>
              </div>
            </div>
          </div>
        ))}

        {error && (
          <div className="border border-red-900 bg-red-950/30 text-red-400 text-xs font-mono p-3 mt-2">
            {error}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-surface-300 px-6 py-4 shrink-0">
        <div className="flex gap-px max-w-4xl">
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isStreaming ? "Generating..." : "Type a message..."}
              disabled={isStreaming || !selectedModel}
              rows={1}
              className="input-field w-full resize-none disabled:opacity-40 pr-4"
              style={{ minHeight: "44px", maxHeight: "200px" }}
            />
          </div>
          <button
            onClick={handleSend}
            disabled={isStreaming || !input.trim() || !selectedModel}
            className="btn-primary disabled:opacity-30 shrink-0"
          >
            {isStreaming ? "..." : "Send"}
          </button>
        </div>
        <p className="text-[10px] font-mono text-surface-700 mt-2">
          Enter to send. Shift+Enter for new line.
        </p>
      </div>
    </div>
  );
}
