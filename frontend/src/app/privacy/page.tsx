import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy — UnchainedAPI",
};

export default function PrivacyPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-20">
      <p className="section-label mb-4">// Legal</p>
      <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-2">
        Privacy Policy<span className="text-terminal-500">.</span>
      </h1>
      <p className="text-xs font-mono text-surface-800 mb-12">Last updated: March 5, 2026</p>

      <div className="space-y-10 text-sm text-surface-900 leading-relaxed font-mono">
        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">1. Introduction</h2>
          <p>
            This Privacy Policy describes how UnchainedAPI (&quot;we&quot;, &quot;us&quot;) collects, uses,
            and protects your information when you use llm.ai-vfx.com and associated API services
            (&quot;Service&quot;).
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">2. Information We Collect</h2>

          <h3 className="text-neutral-300 text-sm font-semibold mt-4 mb-2">Account Data</h3>
          <p>
            When you register, we collect your email address and a hashed password (bcrypt).
            We do not store plaintext passwords.
          </p>

          <h3 className="text-neutral-300 text-sm font-semibold mt-4 mb-2">Payment Data</h3>
          <p>
            Payments are processed by Paddle (our Merchant of Record). We do not store your credit card
            numbers or billing address. Paddle handles all payment data subject to their own privacy policy.
            We receive transaction confirmations and credit amounts from Paddle via webhooks.
          </p>

          <h3 className="text-neutral-300 text-sm font-semibold mt-4 mb-2">Usage Data</h3>
          <p>
            We log API usage including: model used, token counts (input/output), GPU time consumed,
            cost, and timestamps. This data is associated with your account for billing and displayed
            in your dashboard.
          </p>

          <h3 className="text-neutral-300 text-sm font-semibold mt-4 mb-2">API Request Content</h3>
          <p>
            We do <span className="text-terminal-400">not</span> store the content of your API requests
            or model responses. Prompts and completions pass through our proxy to the inference backend
            and are not logged, saved, or used for training. Requests are processed in real-time and
            discarded after delivery.
          </p>

          <h3 className="text-neutral-300 text-sm font-semibold mt-4 mb-2">Technical Data</h3>
          <p>
            Standard web server logs may include IP addresses, user agents, and request timestamps.
            These are used for security, debugging, and abuse prevention.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">3. How We Use Your Data</h2>
          <ul className="list-none space-y-2 text-surface-800">
            <li><span className="text-terminal-600 mr-2">&gt;</span>Provide and operate the Service</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Process billing and credit transactions</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Display usage statistics in your dashboard</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Enforce rate limits and prevent abuse</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Communicate service updates or security notices</li>
          </ul>
          <p className="mt-3">
            We do not sell your data. We do not use your data for advertising. We do not share your data
            with third parties except as required to operate the Service (Paddle for payments, RunPod for
            inference).
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">4. Data Retention</h2>
          <p>
            Account data is retained as long as your account is active. Usage logs are retained indefinitely
            for billing records. If you delete your account, we will remove your personal data within 30 days,
            except where retention is required by law or for legitimate business purposes (e.g., financial
            records).
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">5. Data Security</h2>
          <p>
            We implement security measures including: encrypted connections (TLS), hashed passwords (bcrypt),
            hashed API keys (SHA-256), and rate limiting. However, no system is 100% secure. You are
            responsible for keeping your API keys confidential.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">6. Third-Party Services</h2>
          <div className="border border-surface-400 mt-3">
            <div className="grid grid-cols-2 border-b border-surface-400 text-xs uppercase tracking-widest text-surface-700">
              <div className="p-3 border-r border-surface-400">Service</div>
              <div className="p-3">Purpose</div>
            </div>
            <div className="grid grid-cols-2 border-b border-surface-300 text-surface-800">
              <div className="p-3 border-r border-surface-300">Paddle</div>
              <div className="p-3">Payment processing (Merchant of Record)</div>
            </div>
            <div className="grid grid-cols-2 border-b border-surface-300 text-surface-800">
              <div className="p-3 border-r border-surface-300">RunPod</div>
              <div className="p-3">GPU inference infrastructure</div>
            </div>
            <div className="grid grid-cols-2 text-surface-800">
              <div className="p-3 border-r border-surface-300">HuggingFace</div>
              <div className="p-3">Model discovery and metadata</div>
            </div>
          </div>
          <p className="mt-3">
            Each third-party service operates under its own privacy policy. We only share the minimum
            data necessary for each service to function.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">7. Cookies</h2>
          <p>
            We use a JWT token stored in localStorage for authentication. We do not use tracking cookies,
            analytics scripts, or third-party advertising pixels.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">8. Your Rights</h2>
          <p>You have the right to:</p>
          <ul className="list-none mt-3 space-y-2 text-surface-800">
            <li><span className="text-terminal-600 mr-2">&gt;</span>Access your personal data (visible in your dashboard)</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Request correction of inaccurate data</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Request deletion of your account and associated data</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Export your usage data</li>
          </ul>
          <p className="mt-3">
            To exercise these rights, contact{" "}
            <a href="mailto:support@llm.ai-vfx.com" className="text-terminal-400 hover:underline">
              support@llm.ai-vfx.com
            </a>.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">9. Changes</h2>
          <p>
            We may update this Privacy Policy from time to time. Changes will be posted on this page
            with an updated date. Continued use of the Service constitutes acceptance.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">10. Contact</h2>
          <p>
            For privacy-related inquiries, contact us at{" "}
            <a href="mailto:support@llm.ai-vfx.com" className="text-terminal-400 hover:underline">
              support@llm.ai-vfx.com
            </a>.
          </p>
        </section>
      </div>

      <div className="mt-16 pt-8 border-t border-surface-300 flex gap-6">
        <Link href="/terms" className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors">
          Terms of Service
        </Link>
        <Link href="/refund" className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors">
          Refund Policy
        </Link>
      </div>
    </div>
  );
}
