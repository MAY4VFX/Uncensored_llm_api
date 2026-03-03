import CodeExample from "@/components/CodeExample";

export default function DocsPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-12">
      <h1 className="text-3xl font-bold text-white mb-2">API Documentation</h1>
      <p className="text-gray-400 mb-10">
        UnchainedAPI is fully compatible with the OpenAI Chat Completions API.
      </p>

      {/* Quick Start */}
      <section className="mb-12">
        <h2 className="text-2xl font-semibold text-white mb-4">Quick Start</h2>
        <ol className="list-decimal list-inside text-gray-300 space-y-3">
          <li>
            <strong className="text-white">Create an account</strong> at{" "}
            <code className="text-brand-400">/register</code>
          </li>
          <li>
            <strong className="text-white">Generate an API key</strong> from your dashboard
          </li>
          <li>
            <strong className="text-white">Make API calls</strong> using any OpenAI-compatible SDK
          </li>
        </ol>
      </section>

      {/* Code Examples */}
      <section className="mb-12">
        <h2 className="text-2xl font-semibold text-white mb-4">Code Examples</h2>
        <CodeExample />
      </section>

      {/* Endpoints */}
      <section className="mb-12">
        <h2 className="text-2xl font-semibold text-white mb-6">API Endpoints</h2>

        <div className="space-y-6">
          <div className="glass-card p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-green-500/20 text-green-400 px-2 py-0.5 rounded text-xs font-mono">GET</span>
              <code className="text-white">/v1/models</code>
            </div>
            <p className="text-gray-400 text-sm">
              List all available models. Returns OpenAI-compatible model list.
            </p>
          </div>

          <div className="glass-card p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded text-xs font-mono">POST</span>
              <code className="text-white">/v1/chat/completions</code>
            </div>
            <p className="text-gray-400 text-sm mb-3">
              Create a chat completion. Supports streaming via SSE.
            </p>
            <h4 className="text-white text-sm font-medium mb-2">Headers</h4>
            <pre className="bg-gray-800 rounded-lg p-3 text-sm text-gray-300 overflow-x-auto mb-3">
{`Authorization: Bearer sk-unch-your-key
Content-Type: application/json`}
            </pre>
            <h4 className="text-white text-sm font-medium mb-2">Request Body</h4>
            <pre className="bg-gray-800 rounded-lg p-3 text-sm text-gray-300 overflow-x-auto">
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

          <div className="glass-card p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded text-xs font-mono">POST</span>
              <code className="text-white">/auth/register</code>
            </div>
            <p className="text-gray-400 text-sm">Create a new account. Returns JWT access token.</p>
          </div>

          <div className="glass-card p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded text-xs font-mono">POST</span>
              <code className="text-white">/auth/login</code>
            </div>
            <p className="text-gray-400 text-sm">Sign in and get a JWT access token.</p>
          </div>

          <div className="glass-card p-6">
            <div className="flex items-center gap-3 mb-3">
              <span className="bg-green-500/20 text-green-400 px-2 py-0.5 rounded text-xs font-mono">GET</span>
              <code className="text-white">/usage/me</code>
            </div>
            <p className="text-gray-400 text-sm">Get your usage statistics and remaining credits.</p>
          </div>
        </div>
      </section>

      {/* Error Codes */}
      <section className="mb-12">
        <h2 className="text-2xl font-semibold text-white mb-4">Error Codes</h2>
        <div className="glass-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="px-6 py-3 text-left text-gray-400">Code</th>
                <th className="px-6 py-3 text-left text-gray-400">Meaning</th>
              </tr>
            </thead>
            <tbody className="text-gray-300">
              <tr className="border-b border-gray-800/50">
                <td className="px-6 py-3 font-mono">401</td>
                <td className="px-6 py-3">Invalid or missing API key</td>
              </tr>
              <tr className="border-b border-gray-800/50">
                <td className="px-6 py-3 font-mono">402</td>
                <td className="px-6 py-3">Insufficient credits — top up your balance</td>
              </tr>
              <tr className="border-b border-gray-800/50">
                <td className="px-6 py-3 font-mono">404</td>
                <td className="px-6 py-3">Model not found or not active</td>
              </tr>
              <tr className="border-b border-gray-800/50">
                <td className="px-6 py-3 font-mono">429</td>
                <td className="px-6 py-3">Rate limit exceeded — check Retry-After header</td>
              </tr>
              <tr>
                <td className="px-6 py-3 font-mono">503</td>
                <td className="px-6 py-3">Model endpoint not available (cold start or error)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
