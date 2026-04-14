import CodeExample from "@/components/CodeExample";

const BASE_URL = "https://llm.ai-vfx.com/api/v1";

export default function DocsPage() {
  return (
    <div className="max-w-4xl mx-auto px-6 py-16">
      <p className="section-label mb-4">// Reference</p>
      <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-2">
        API Documentation<span className="text-terminal-500 animate-blink">_</span>
      </h1>
      <p className="text-sm font-mono text-surface-800 mb-4">
        UnchainedAPI is fully compatible with the OpenAI Chat Completions API.
      </p>
      <div className="border border-surface-400 bg-surface-100 p-4 mb-12 text-sm font-mono text-neutral-300">
        <p className="text-xs uppercase tracking-[0.2em] text-surface-900 mb-1">// Base URL</p>
        <code className="text-terminal-400">{BASE_URL}</code>
      </div>

      {/* Quick Start */}
      <section className="mb-12">
        <p className="section-label mb-4">// Quick Start</p>
        <ol className="list-none text-neutral-300 font-mono text-sm space-y-3">
          <li className="flex items-start gap-3">
            <span className="text-terminal-500 font-bold">01</span>
            <span>
              <strong className="text-neutral-100">Create an account</strong> at{" "}
              <code className="text-terminal-400">/register</code>
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="text-terminal-500 font-bold">02</span>
            <span>
              <strong className="text-neutral-100">Generate an API key</strong> from your dashboard
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="text-terminal-500 font-bold">03</span>
            <span>
              <strong className="text-neutral-100">Make API calls</strong> using any OpenAI-compatible SDK
            </span>
          </li>
        </ol>
      </section>

      {/* Code Examples */}
      <section className="mb-12">
        <p className="section-label mb-4">// Code Examples</p>
        <CodeExample />
      </section>

      {/* Connecting Agents */}
      <section className="mb-12">
        <p className="section-label mb-4">// Connecting Agents & Clients</p>
        <p className="text-sm font-mono text-surface-800 mb-6">
          UnchainedAPI speaks the OpenAI protocol, so any tool with an
          &quot;OpenAI-compatible&quot; option works. Use the base URL and your
          <code className="text-terminal-400 mx-1">sk-unch-</code> key from the dashboard.
        </p>

        <div className="space-y-6">
          <div className="border border-surface-400 bg-surface-100 p-6">
            <h3 className="text-neutral-100 font-mono font-bold mb-3">Cline / Continue.dev / Roo Code (VS Code)</h3>
            <ol className="text-sm font-mono text-surface-900 space-y-1 list-decimal list-inside">
              <li>Provider: <span className="text-terminal-400">OpenAI Compatible</span></li>
              <li>Base URL: <code className="text-terminal-400">{BASE_URL}</code></li>
              <li>API Key: <code className="text-terminal-400">sk-unch-...</code></li>
              <li>Model ID: copy slug from <code className="text-terminal-400">/models</code></li>
            </ol>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <h3 className="text-neutral-100 font-mono font-bold mb-3">Cursor</h3>
            <p className="text-sm font-mono text-surface-900 mb-2">
              Settings → Models → OpenAI API Key → Override OpenAI Base URL
            </p>
            <pre className="bg-surface-0 border border-surface-400 p-3 text-sm text-neutral-300 font-mono overflow-x-auto">
{`Base URL:  ${BASE_URL}
API Key:   sk-unch-your-key-here
Model:     <slug from /models>`}
            </pre>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <h3 className="text-neutral-100 font-mono font-bold mb-3">Open WebUI</h3>
            <p className="text-sm font-mono text-surface-900 mb-2">
              Settings → Connections → OpenAI API
            </p>
            <pre className="bg-surface-0 border border-surface-400 p-3 text-sm text-neutral-300 font-mono overflow-x-auto">
{`API Base URL:  ${BASE_URL}
API Key:       sk-unch-your-key-here`}
            </pre>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <h3 className="text-neutral-100 font-mono font-bold mb-3">LibreChat / BetterChatGPT / ChatBox / Jan / AnythingLLM</h3>
            <p className="text-sm font-mono text-surface-900">
              Pick the <span className="text-terminal-400">OpenAI</span> or
              <span className="text-terminal-400"> Custom OpenAI</span> provider and plug in the same
              base URL and key. No extra configuration required.
            </p>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <h3 className="text-neutral-100 font-mono font-bold mb-3">Environment variables (openai SDK, LangChain, LlamaIndex)</h3>
            <pre className="bg-surface-0 border border-surface-400 p-3 text-sm text-neutral-300 font-mono overflow-x-auto">
{`export OPENAI_API_KEY=sk-unch-your-key-here
export OPENAI_BASE_URL=${BASE_URL}`}
            </pre>
          </div>
        </div>
      </section>

      {/* Endpoints */}
      <section className="mb-12">
        <p className="section-label mb-6">// API Endpoints</p>

        <div className="space-y-6">
          <div className="border border-surface-400 bg-surface-100 p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-terminal-600/20 text-terminal-400 px-2 py-0.5 text-xs font-mono uppercase tracking-[0.2em]">GET</span>
              <code className="text-neutral-100 font-mono">/v1/models</code>
            </div>
            <p className="text-surface-800 text-sm font-mono">
              List all available models. Returns OpenAI-compatible model list.
            </p>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-blue-500/20 text-blue-400 px-2 py-0.5 text-xs font-mono uppercase tracking-[0.2em]">POST</span>
              <code className="text-neutral-100 font-mono">/v1/chat/completions</code>
            </div>
            <p className="text-surface-800 text-sm font-mono mb-4">
              Create a chat completion. Supports streaming via SSE.
            </p>
            <p className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2">Headers</p>
            <pre className="bg-surface-0 border border-surface-400 p-3 text-sm text-neutral-300 font-mono overflow-x-auto mb-4">
{`Authorization: Bearer sk-unch-your-key
Content-Type: application/json`}
            </pre>
            <p className="text-xs font-mono uppercase tracking-[0.2em] text-surface-900 mb-2">Request Body</p>
            <pre className="bg-surface-0 border border-surface-400 p-3 text-sm text-neutral-300 font-mono overflow-x-auto">
{`{
  "model": "model-slug",      // Required: model identifier
  "messages": [                // Required: conversation messages
    {"role": "user", "content": "Hello!"}
  ],
  "temperature": 0.7,         // Optional: 0.0-2.0 (default: 1.0)
  "max_tokens": 2048,         // Optional: max output tokens
  "top_p": 1.0,               // Optional: nucleus sampling
  "stream": false,             // Optional: enable SSE streaming
  "stop": null                 // Optional: stop sequences
}`}
            </pre>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-blue-500/20 text-blue-400 px-2 py-0.5 text-xs font-mono uppercase tracking-[0.2em]">POST</span>
              <code className="text-neutral-100 font-mono">/auth/register</code>
            </div>
            <p className="text-surface-800 text-sm font-mono">Create a new account. Returns JWT access token.</p>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-blue-500/20 text-blue-400 px-2 py-0.5 text-xs font-mono uppercase tracking-[0.2em]">POST</span>
              <code className="text-neutral-100 font-mono">/auth/login</code>
            </div>
            <p className="text-surface-800 text-sm font-mono">Sign in and get a JWT access token.</p>
          </div>

          <div className="border border-surface-400 bg-surface-100 p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-terminal-600/20 text-terminal-400 px-2 py-0.5 text-xs font-mono uppercase tracking-[0.2em]">GET</span>
              <code className="text-neutral-100 font-mono">/usage/me</code>
            </div>
            <p className="text-surface-800 text-sm font-mono">Get your usage statistics and remaining credits.</p>
          </div>
        </div>
      </section>

      {/* Error Codes */}
      <section className="mb-12">
        <p className="section-label mb-4">// Error Codes</p>
        <div className="border border-surface-400 bg-surface-100 overflow-hidden">
          <table className="w-full text-sm font-mono">
            <thead>
              <tr className="border-b border-surface-400">
                <th className="px-6 py-3 text-left text-xs uppercase tracking-[0.2em] text-surface-900">Code</th>
                <th className="px-6 py-3 text-left text-xs uppercase tracking-[0.2em] text-surface-900">Meaning</th>
              </tr>
            </thead>
            <tbody className="text-neutral-300">
              <tr className="border-b border-surface-300">
                <td className="px-6 py-3 text-terminal-400">401</td>
                <td className="px-6 py-3">Invalid or missing API key</td>
              </tr>
              <tr className="border-b border-surface-300">
                <td className="px-6 py-3 text-terminal-400">402</td>
                <td className="px-6 py-3">Insufficient credits -- top up your balance</td>
              </tr>
              <tr className="border-b border-surface-300">
                <td className="px-6 py-3 text-terminal-400">404</td>
                <td className="px-6 py-3">Model not found or not active</td>
              </tr>
              <tr className="border-b border-surface-300">
                <td className="px-6 py-3 text-terminal-400">429</td>
                <td className="px-6 py-3">Rate limit exceeded -- check Retry-After header</td>
              </tr>
              <tr>
                <td className="px-6 py-3 text-terminal-400">503</td>
                <td className="px-6 py-3">Model endpoint not available (cold start or error)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
