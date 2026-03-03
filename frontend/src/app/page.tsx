import Link from "next/link";
import CodeExample from "@/components/CodeExample";

export default function Home() {
  return (
    <div>
      {/* Hero */}
      <section className="relative border-b border-surface-300">
        <div className="max-w-7xl mx-auto px-6 py-28 sm:py-36">
          <p className="section-label mb-6">// OpenAI-compatible endpoint</p>
          <h1 className="text-5xl sm:text-7xl font-mono font-bold mb-6 leading-tight">
            <span className="text-glow">Unchained</span>
            <br />
            <span className="text-neutral-200">LLM Access</span>
            <span className="text-terminal-500 animate-blink">_</span>
          </h1>
          <p className="text-surface-900 text-lg max-w-xl mb-12 leading-relaxed">
            Uncensored and abliterated models. Auto-discovered from HuggingFace.
            Serverless GPU. Pay per token. No restrictions.
          </p>
          <div className="flex gap-4">
            <Link href="/register" className="btn-primary">
              Get Access
            </Link>
            <Link href="/playground" className="btn-secondary">
              Try Playground
            </Link>
          </div>
        </div>
      </section>

      {/* Stats bar */}
      <section className="border-b border-surface-300">
        <div className="max-w-7xl mx-auto px-6 grid grid-cols-2 md:grid-cols-4">
          {[
            ["Models", "50+"],
            ["Latency", "<2s cold start"],
            ["Uptime", "99.9%"],
            ["Cost", "$0/idle"],
          ].map(([label, value], i) => (
            <div
              key={label}
              className={`py-6 px-4 ${i < 3 ? "border-r border-surface-300" : ""}`}
            >
              <p className="text-xs font-mono uppercase tracking-widest text-surface-800 mb-1">{label}</p>
              <p className="text-lg font-mono text-terminal-400">{value}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="max-w-7xl mx-auto px-6 py-24">
        <p className="section-label mb-8">// Core features</p>
        <div className="grid md:grid-cols-3 gap-px bg-surface-300">
          {[
            {
              title: "OpenAI Compatible",
              desc: "Drop-in replacement. Use existing SDKs and tools. Change the base URL, keep your code.",
              tag: "PROTOCOL",
            },
            {
              title: "Auto-Discovery",
              desc: "Scout agent monitors HuggingFace around the clock. New uncensored models deployed automatically.",
              tag: "AUTOMATION",
            },
            {
              title: "Pay Per Token",
              desc: "Serverless GPU. No idle costs. Starting at $0.39 per 1M output tokens for 7B models.",
              tag: "BILLING",
            },
          ].map((f) => (
            <div key={f.title} className="bg-surface-50 p-8 hover:bg-surface-100 transition-colors">
              <p className="text-xs font-mono text-terminal-600 uppercase tracking-widest mb-4">{f.tag}</p>
              <h3 className="text-lg font-mono font-semibold text-neutral-100 mb-3">{f.title}</h3>
              <p className="text-surface-900 text-sm leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="border-y border-surface-300">
        <div className="max-w-7xl mx-auto px-6 py-24">
          <p className="section-label mb-8">// Request flow</p>
          <div className="font-mono text-sm text-surface-800 space-y-2 max-w-2xl">
            <p><span className="text-terminal-400">$</span> curl api.unchained.ai/v1/chat/completions \</p>
            <p className="pl-6">-H &quot;Authorization: Bearer <span className="text-terminal-500">sk-unch-...</span>&quot; \</p>
            <p className="pl-6">-d &apos;&#123;&quot;model&quot;: &quot;<span className="text-neutral-300">glm-4-heretic</span>&quot;, ...&#125;&apos;</p>
            <p className="mt-4 text-surface-700">
              <span className="text-surface-600">[1]</span> Validate API key{" "}
              <span className="text-surface-600">[2]</span> Check credits{" "}
              <span className="text-surface-600">[3]</span> Rate limit{" "}
              <span className="text-surface-600">[4]</span> Proxy to RunPod vLLM{" "}
              <span className="text-surface-600">[5]</span> Stream response{" "}
              <span className="text-surface-600">[6]</span> Log usage
            </p>
          </div>
        </div>
      </section>

      {/* Code Example */}
      <section className="max-w-4xl mx-auto px-6 py-24">
        <p className="section-label mb-2">// Integration</p>
        <h2 className="text-2xl font-mono font-bold text-neutral-100 mb-8">
          Two lines to switch<span className="text-terminal-500">.</span>
        </h2>
        <CodeExample />
      </section>

      {/* Pricing */}
      <section className="border-y border-surface-300">
        <div className="max-w-7xl mx-auto px-6 py-24">
          <p className="section-label mb-8">// Pricing</p>
          <div className="grid md:grid-cols-3 gap-px bg-surface-300">
            {[
              { name: "Pay As You Go", price: "$5+", desc: "Prepaid credits. Any model.", tag: null },
              { name: "Pro", price: "$49/mo", desc: "25M tokens. All models. Priority.", tag: "POPULAR" },
              { name: "Business", price: "$149/mo", desc: "100M tokens. Priority queues.", tag: null },
            ].map((plan) => (
              <div key={plan.name} className="bg-surface-50 p-8 relative">
                {plan.tag && (
                  <span className="absolute top-4 right-4 text-[10px] font-mono text-terminal-500 uppercase tracking-widest">
                    {plan.tag}
                  </span>
                )}
                <p className="text-xs font-mono text-surface-800 uppercase tracking-widest mb-4">{plan.name}</p>
                <p className="text-3xl font-mono font-bold text-neutral-100 mb-4">{plan.price}</p>
                <p className="text-surface-900 text-sm">{plan.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-surface-300">
        <div className="max-w-7xl mx-auto px-6 py-8 flex justify-between items-center">
          <span className="text-xs font-mono text-surface-700 uppercase tracking-widest">
            Unchained_API
          </span>
          <div className="flex gap-8">
            <Link href="/docs" className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors">
              Docs
            </Link>
            <Link href="/models" className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors">
              Models
            </Link>
            <Link href="/playground" className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors">
              Playground
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
