"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { getToken, isAuthenticated } from "@/lib/auth";
import { getMe } from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

interface ModelOption {
  id: string;
  name: string;
  maxContext: number;
}

type WorkerStatus = "ready" | "sleep" | "warming_up" | "throttled" | "unknown" | "loading" | null;

// --- Think tag parser ---
function ThinkBlock({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-[11px] font-mono text-surface-600 hover:text-surface-800 transition-colors"
      >
        <span className="text-[10px]">{open ? "\u25BC" : "\u25B6"}</span>
        <span className="uppercase tracking-wider">Reasoning</span>
      </button>
      {open && (
        <div className="mt-1 bg-surface-50 border-l-2 border-surface-500 pl-3 py-2 text-surface-700 text-xs font-mono whitespace-pre-wrap leading-relaxed">
          {content}
        </div>
      )}
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-[11px] font-mono text-surface-600">
      <span className="inline-block w-3 h-3 border border-surface-500 border-t-terminal-500 rounded-full animate-spin" />
      <span className="uppercase tracking-wider">Thinking...</span>
    </div>
  );
}

function renderMessageContent(content: string, isStreaming: boolean) {
  const thinkOpenIdx = content.indexOf("<think>");
  if (thinkOpenIdx === -1) {
    return <span>{content}</span>;
  }

  const thinkCloseIdx = content.indexOf("</think>");
  const before = content.slice(0, thinkOpenIdx);

  if (thinkCloseIdx === -1) {
    // Still thinking (streaming, no close tag yet)
    const thinkContent = content.slice(thinkOpenIdx + 7);
    return (
      <>
        {before && <span>{before}</span>}
        {isStreaming ? <ThinkingIndicator /> : <ThinkBlock content={thinkContent} />}
      </>
    );
  }

  const thinkContent = content.slice(thinkOpenIdx + 7, thinkCloseIdx);
  const after = content.slice(thinkCloseIdx + 8);

  return (
    <>
      {before && <span>{before}</span>}
      <ThinkBlock content={thinkContent} />
      <span>{after}</span>
    </>
  );
}

// --- Status bar ---
function StatusBar({ status }: { status: WorkerStatus }) {
  if (status === "ready" || status === "loading" || status === "unknown" || !status) return null;

  const config: Record<string, { text: string; color: string; spin: boolean }> = {
    sleep: { text: "Model is sleeping. Will wake on request.", color: "text-blue-400", spin: false },
    warming_up: { text: "Waking up model... (~1-2 min)", color: "text-yellow-400", spin: true },
    throttled: { text: "GPU unavailable. Try later.", color: "text-red-400", spin: false },
  };
  const c = config[status];
  if (!c) return null;

  return (
    <div className={`px-6 py-2 border-t border-surface-300 flex items-center gap-2 ${c.color} font-mono text-xs shrink-0`}>
      {c.spin && (
        <span className="inline-block w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
      )}
      <span>{c.text}</span>
    </div>
  );
}

// --- Scroll-to-bottom button ---
function ScrollButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="absolute bottom-4 right-6 w-8 h-8 bg-surface-200 border border-surface-400 text-surface-800 hover:text-terminal-400 hover:border-terminal-500/60 flex items-center justify-center font-mono text-sm transition-colors"
      title="Scroll to bottom"
    >
      ↓
    </button>
  );
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
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus>(null);

  // Auto-scroll refs
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);

  // Polling ref
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const API_URL = "/api";

  // --- Smart scroll ---
  const scrollToBottom = useCallback(() => {
    const el = messagesContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  const handleScroll = useCallback(() => {
    const el = messagesContainerRef.current;
    if (!el) return;
    const threshold = 100;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    setIsNearBottom(atBottom);
  }, []);

  // Auto-scroll when messages change, only if near bottom
  useEffect(() => {
    if (isNearBottom) scrollToBottom();
  }, [messages, isNearBottom, scrollToBottom]);

  // --- Status polling ---
  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const startPolling = useCallback((model: string) => {
    stopPolling();
    pollIntervalRef.current = setInterval(() => {
      fetch(`${API_URL}/v1/models/${encodeURIComponent(model)}/status`)
        .then((r) => r.json())
        .then((data) => {
          const s = data.status as string;
          const mapped: WorkerStatus = s === "cold" ? "sleep" : (s as WorkerStatus);
          setWorkerStatus(mapped);
          if (mapped === "ready") stopPolling();
        })
        .catch(() => {});
    }, 5000);
  }, [API_URL, stopPolling]);

  // Cleanup polling on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  // --- Init ---
  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
      return;
    }
    const token = getToken()!;
    getMe(token).then(setUser).catch(() => router.push("/login"));

    fetch(`${API_URL}/v1/models`)
      .then((r) => r.json())
      .then((data) => {
        const modelList = data.data?.map((m: any) => ({ id: m.id, name: m.id, maxContext: m.max_context_length || 4096 })) || [];
        setModels(modelList);
        if (modelList.length > 0) setSelectedModel(modelList[0].id);
      })
      .catch(() => {});
  }, [router, API_URL]);

  // --- Check status + pre-warm on model change ---
  useEffect(() => {
    if (!selectedModel) {
      setWorkerStatus(null);
      stopPolling();
      return;
    }
    setWorkerStatus("loading");
    fetch(`${API_URL}/v1/models/${encodeURIComponent(selectedModel)}/status`)
      .then((r) => r.json())
      .then((data) => {
        const s = data.status as string;
        const mapped: WorkerStatus = s === "cold" ? "sleep" : (s as WorkerStatus);
        setWorkerStatus(mapped);

        // Pre-warm if sleeping
        if (mapped === "sleep") {
          const token = getToken();
          if (token) {
            setWorkerStatus("warming_up");
            fetch(`${API_URL}/v1/models/${encodeURIComponent(selectedModel)}/warm`, {
              method: "POST",
              headers: { Authorization: `Bearer ${token}` },
            }).catch(() => {});
            startPolling(selectedModel);
          }
        }
      })
      .catch(() => setWorkerStatus("unknown"));
  }, [selectedModel, API_URL, startPolling, stopPolling]);

  // --- Send message ---
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
      let firstTokenReceived = false;

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

                // Handle status events
                if (parsed.object === "status") {
                  const statusMsg = parsed.status as string;
                  if (statusMsg === "ready") {
                    setWorkerStatus("ready");
                    stopPolling();
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId ? { ...m, content: "" } : m
                      )
                    );
                  } else {
                    if (statusMsg === "IN_QUEUE") setWorkerStatus("warming_up");
                    else if (statusMsg === "IN_PROGRESS") setWorkerStatus("warming_up");
                    else setWorkerStatus(statusMsg as WorkerStatus);
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === assistantId
                          ? { ...m, content: parsed.message || "Processing..." }
                          : m
                      )
                    );
                  }
                  continue;
                }

                const delta = parsed.choices?.[0]?.delta?.content;
                if (delta) {
                  if (!firstTokenReceived) {
                    firstTokenReceived = true;
                    setWorkerStatus("ready");
                    stopPolling();
                  }
                  setMessages((prev) =>
                    prev.map((m) => {
                      if (m.id !== assistantId) return m;
                      const isStatus = m.content.startsWith("Waiting ") || m.content.startsWith("Worker ") || m.content.startsWith("Status:") || m.content.startsWith("Processing");
                      return { ...m, content: (isStatus ? "" : m.content) + delta };
                    })
                  );
                }
              } catch {
                // Skip malformed SSE chunks
              }
            }
          }
        }
      }

      // Refresh credits + final status check
      getMe(token).then(setUser);
      fetch(`${API_URL}/v1/models/${encodeURIComponent(selectedModel)}/status`)
        .then((r) => r.json())
        .then((data) => {
          const s = data.status as string;
          setWorkerStatus(s === "cold" ? "sleep" : (s as WorkerStatus));
        })
        .catch(() => {});
    } catch (err: any) {
      setError(err.message);
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

  const inputDisabled = isStreaming || !selectedModel || workerStatus === "warming_up" || workerStatus === "throttled";

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

          {workerStatus && workerStatus !== "loading" && (
            <span
              className={`text-[10px] font-mono uppercase tracking-wider px-2 py-0.5 border ${
                workerStatus === "ready"
                  ? "text-green-400 border-green-800 bg-green-950/40"
                  : workerStatus === "sleep"
                  ? "text-blue-400 border-blue-800 bg-blue-950/40"
                  : workerStatus === "warming_up"
                  ? "text-yellow-400 border-yellow-800 bg-yellow-950/40"
                  : workerStatus === "throttled"
                  ? "text-red-400 border-red-800 bg-red-950/40"
                  : "text-surface-700 border-surface-400"
              }`}
            >
              {workerStatus === "ready" && "Ready"}
              {workerStatus === "sleep" && "Sleep"}
              {workerStatus === "warming_up" && "Warming up..."}
              {workerStatus === "throttled" && "Throttled"}
              {workerStatus === "unknown" && "Status unknown"}
            </span>
          )}
          {workerStatus === "loading" && (
            <span className="text-[10px] font-mono text-surface-700">checking...</span>
          )}

          {selectedModel && (() => {
            const ctx = models.find((m) => m.id === selectedModel)?.maxContext || 4096;
            return (
              <span className="text-[10px] font-mono text-surface-600">
                ctx: {ctx >= 1024 ? `${Math.floor(ctx / 1024)}k` : ctx}
              </span>
            );
          })()}
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
      <div
        ref={messagesContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-6 py-4 space-y-1 relative"
      >
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
                <div className="text-sm text-neutral-300 font-mono whitespace-pre-wrap break-words leading-relaxed">
                  {m.role === "assistant"
                    ? renderMessageContent(m.content, isStreaming)
                    : m.content}
                  {m.role === "assistant" && isStreaming && m.content === "" && (
                    <span className="text-terminal-500 animate-blink">
                      {workerStatus === "sleep" || workerStatus === "warming_up" || workerStatus === "throttled"
                        ? "..."
                        : "_"}
                    </span>
                  )}
                  {m.role === "assistant" && isStreaming && m.content !== "" && !m.content.includes("<think>") && workerStatus !== "sleep" && workerStatus !== "warming_up" && workerStatus !== "throttled" && (
                    <span className="text-terminal-500 animate-blink">|</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}

        {error && (
          <div className="border border-red-900 bg-red-950/30 text-red-400 text-xs font-mono p-3 mt-2">
            {error}
          </div>
        )}

        {/* Scroll to bottom button */}
        {!isNearBottom && messages.length > 0 && (
          <ScrollButton onClick={scrollToBottom} />
        )}
      </div>

      {/* Status bar */}
      <StatusBar status={workerStatus} />

      {/* Input */}
      <div className="border-t border-surface-300 px-6 py-4 shrink-0">
        <div className="flex gap-px max-w-4xl">
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isStreaming
                  ? "Generating..."
                  : workerStatus === "warming_up"
                  ? "Waiting for model to wake up..."
                  : workerStatus === "throttled"
                  ? "GPU unavailable..."
                  : "Type a message..."
              }
              disabled={inputDisabled}
              rows={1}
              className="input-field w-full resize-none disabled:opacity-40 pr-4"
              style={{ minHeight: "44px", maxHeight: "200px" }}
            />
          </div>
          <button
            onClick={handleSend}
            disabled={inputDisabled || !input.trim()}
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
