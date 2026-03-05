import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Refund Policy — UnchainedAPI",
};

export default function RefundPage() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-20">
      <p className="section-label mb-4">// Legal</p>
      <h1 className="text-3xl font-mono font-bold text-neutral-100 mb-2">
        Refund Policy<span className="text-terminal-500">.</span>
      </h1>
      <p className="text-xs font-mono text-surface-800 mb-12">Last updated: March 5, 2026</p>

      <div className="space-y-10 text-sm text-surface-900 leading-relaxed font-mono">
        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">1. Credit Purchases</h2>
          <p>
            UnchainedAPI operates on a prepaid credit system. When you purchase credits, they are added
            to your account balance immediately. Credits are used to pay for GPU compute time when you
            make API requests.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">2. Refund Eligibility</h2>
          <p>We offer refunds under the following conditions:</p>

          <div className="mt-4 border border-surface-400">
            <div className="p-4 border-b border-surface-400 bg-surface-100">
              <p className="text-terminal-400 text-xs uppercase tracking-widest mb-2">Full Refund</p>
              <p className="text-surface-800">
                If you have not used any credits from your purchase, you may request a full refund within
                <span className="text-neutral-200"> 14 days</span> of the transaction date.
              </p>
            </div>
            <div className="p-4 border-b border-surface-400">
              <p className="text-terminal-400 text-xs uppercase tracking-widest mb-2">Partial Refund</p>
              <p className="text-surface-800">
                If you have used some credits, we may issue a refund for the unused portion at our
                discretion, within <span className="text-neutral-200">14 days</span> of purchase.
              </p>
            </div>
            <div className="p-4">
              <p className="text-terminal-400 text-xs uppercase tracking-widest mb-2">Service Issues</p>
              <p className="text-surface-800">
                If the Service was significantly unavailable or malfunctioning during your usage period,
                we will credit your account or issue a refund proportional to the affected period,
                regardless of the 14-day window.
              </p>
            </div>
          </div>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">3. Non-Refundable Cases</h2>
          <ul className="list-none space-y-2 text-surface-800">
            <li><span className="text-terminal-600 mr-2">&gt;</span>Credits already consumed by API usage or Keep Warm billing</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Accounts terminated for Terms of Service violations</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Requests made more than 14 days after the purchase date (unless Service issue)</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Dissatisfaction with model outputs (models are third-party open-source; output quality is not guaranteed)</li>
          </ul>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">4. Subscriptions</h2>
          <p>
            If you are on a recurring subscription plan, you may cancel at any time. Cancellation takes
            effect at the end of the current billing period — you retain access until then. We do not
            offer prorated refunds for partial billing periods on subscription plans.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">5. How to Request a Refund</h2>
          <p>
            To request a refund, email{" "}
            <a href="mailto:support@llm.ai-vfx.com" className="text-terminal-400 hover:underline">
              support@llm.ai-vfx.com
            </a>{" "}
            with:
          </p>
          <ul className="list-none mt-3 space-y-2 text-surface-800">
            <li><span className="text-terminal-600 mr-2">&gt;</span>Your account email</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Transaction ID or date of purchase</li>
            <li><span className="text-terminal-600 mr-2">&gt;</span>Reason for the refund request</li>
          </ul>
          <p className="mt-3">
            We aim to respond to refund requests within <span className="text-neutral-200">3 business days</span>.
            Approved refunds are processed through Paddle (our payment processor) and may take
            5–10 business days to appear on your statement.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">6. Chargebacks</h2>
          <p>
            If you believe a charge is unauthorized, please contact us before initiating a chargeback
            with your bank. We are happy to resolve billing disputes directly. Fraudulent chargebacks
            may result in account termination.
          </p>
        </section>

        <section>
          <h2 className="text-neutral-200 text-base font-semibold mb-3">7. Contact</h2>
          <p>
            For billing questions or refund requests:{" "}
            <a href="mailto:support@llm.ai-vfx.com" className="text-terminal-400 hover:underline">
              support@llm.ai-vfx.com
            </a>
          </p>
        </section>
      </div>

      <div className="mt-16 pt-8 border-t border-surface-300 flex gap-6">
        <Link href="/terms" className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors">
          Terms of Service
        </Link>
        <Link href="/privacy" className="text-xs font-mono text-surface-800 hover:text-terminal-400 uppercase tracking-widest transition-colors">
          Privacy Policy
        </Link>
      </div>
    </div>
  );
}
