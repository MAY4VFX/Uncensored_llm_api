import Link from "next/link";
import CodeExample from "@/components/CodeExample";

export default function Home() {
  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-radial from-brand-950/40 via-gray-950 to-gray-950" />
        <div className="relative max-w-7xl mx-auto px-4 py-24 sm:py-32 text-center">
          <div className="inline-block mb-4 px-4 py-1.5 rounded-full bg-brand-500/10 border border-brand-500/20">
            <span className="text-brand-400 text-sm font-medium">OpenAI-Compatible API</span>
          </div>
          <h1 className="text-5xl sm:text-7xl font-bold mb-6">
            <span className="gradient-text">Unchained</span>{" "}
            <span className="text-white">LLM Access</span>
          </h1>
          <p className="text-gray-400 text-lg sm:text-xl max-w-2xl mx-auto mb-10">
            Access uncensored and abliterated LLM models through a simple API.
            New models auto-discovered from HuggingFace. Pay only for what you use.
          </p>
          <div className="flex gap-4 justify-center">
            <Link href="/register" className="btn-primary">
              Get Started Free
            </Link>
            <Link href="/docs" className="btn-secondary">
              View API Docs
            </Link>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-7xl mx-auto px-4 py-20">
        <div className="grid md:grid-cols-3 gap-6">
          <div className="glass-card p-8">
            <div className="w-12 h-12 rounded-xl bg-brand-500/10 flex items-center justify-center mb-4">
              <svg className="w-6 h-6 text-brand-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">OpenAI Compatible</h3>
            <p className="text-gray-400 text-sm">
              Drop-in replacement for OpenAI API. Use your existing SDKs and code — just change the base URL and API key.
            </p>
          </div>

          <div className="glass-card p-8">
            <div className="w-12 h-12 rounded-xl bg-accent-500/10 flex items-center justify-center mb-4">
              <svg className="w-6 h-6 text-accent-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">Auto-Discovery</h3>
            <p className="text-gray-400 text-sm">
              Our scout agent monitors HuggingFace 24/7 for new uncensored models and automatically deploys the best ones.
            </p>
          </div>

          <div className="glass-card p-8">
            <div className="w-12 h-12 rounded-xl bg-purple-500/10 flex items-center justify-center mb-4">
              <svg className="w-6 h-6 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">Pay Per Token</h3>
            <p className="text-gray-400 text-sm">
              Serverless GPU infrastructure. No idle costs. Pay only for the tokens you generate, starting from $0.39/1M tokens.
            </p>
          </div>
        </div>
      </section>

      {/* Code Example */}
      <section className="max-w-4xl mx-auto px-4 py-16">
        <h2 className="text-3xl font-bold text-white text-center mb-2">Start in Minutes</h2>
        <p className="text-gray-400 text-center mb-8">
          Works with any OpenAI SDK. Just change two lines.
        </p>
        <CodeExample />
      </section>

      {/* Pricing teaser */}
      <section className="max-w-7xl mx-auto px-4 py-20">
        <h2 className="text-3xl font-bold text-white text-center mb-12">Simple Pricing</h2>
        <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
          <div className="glass-card p-8 text-center">
            <h3 className="text-lg font-semibold text-white mb-1">Pay As You Go</h3>
            <p className="text-gray-400 text-sm mb-4">Perfect for getting started</p>
            <p className="text-3xl font-bold text-white mb-4">$5<span className="text-lg text-gray-400 font-normal">+</span></p>
            <p className="text-gray-400 text-sm">Prepaid credits, use any model</p>
          </div>

          <div className="glass-card p-8 text-center border-brand-500/30 relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-brand-600 text-white text-xs rounded-full">
              Popular
            </div>
            <h3 className="text-lg font-semibold text-white mb-1">Pro</h3>
            <p className="text-gray-400 text-sm mb-4">For serious developers</p>
            <p className="text-3xl font-bold text-white mb-4">$49<span className="text-lg text-gray-400 font-normal">/mo</span></p>
            <p className="text-gray-400 text-sm">25M tokens, all models, priority</p>
          </div>

          <div className="glass-card p-8 text-center">
            <h3 className="text-lg font-semibold text-white mb-1">Business</h3>
            <p className="text-gray-400 text-sm mb-4">High-volume workloads</p>
            <p className="text-3xl font-bold text-white mb-4">$149<span className="text-lg text-gray-400 font-normal">/mo</span></p>
            <p className="text-gray-400 text-sm">100M tokens, priority queues</p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 mt-20">
        <div className="max-w-7xl mx-auto px-4 py-8 flex justify-between items-center">
          <span className="text-gray-500 text-sm">UnchainedAPI</span>
          <div className="flex gap-6">
            <Link href="/docs" className="text-gray-500 hover:text-gray-300 text-sm">Docs</Link>
            <Link href="/models" className="text-gray-500 hover:text-gray-300 text-sm">Models</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
