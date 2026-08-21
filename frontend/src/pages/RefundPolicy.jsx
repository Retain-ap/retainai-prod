import React from "react";

export default function RefundPolicy() {
  return (
    <div className="min-h-screen bg-[#181a1b] text-gray-100">
      <main className="max-w-3xl mx-auto pt-16 pb-20 px-4">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-yellow-400 mb-3">RetainAI legal</p>
        <h1 className="text-3xl md:text-4xl font-bold text-yellow-400 mb-3">Refund &amp; Cancellation Policy</h1>
        <p className="text-sm text-gray-400 mb-8">Effective August 21, 2026</p>

        <p className="mb-6">This policy explains how RetainAI trials, renewals, cancellations, and refund requests work.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">1. Free trial</h2>
        <p className="mb-6">Eligible new customers receive the trial period displayed at checkout. A payment method may be required. Unless cancelled before the displayed trial end, the paid subscription starts automatically and the payment method is charged. Introductory trial eligibility is limited to one per person or business unless RetainAI approves an exception.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">2. Recurring billing</h2>
        <p className="mb-6">Paid plans automatically renew at the price, tax, currency, and billing interval shown at checkout until cancelled. Your renewal date is based on when paid service begins.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">3. Cancellation</h2>
        <p className="mb-6">Cancel from Settings → Billing or the Stripe billing portal. Cancellation stops future renewals and normally takes effect at the end of the current paid period. Account deletion is separate from cancellation; confirm your subscription status before deleting data.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">4. Refunds</h2>
        <p className="mb-3">Charges are generally non-refundable after a billing period begins. RetainAI will review timely requests involving:</p>
        <ul className="list-disc ml-6 mb-6 space-y-2">
          <li>a duplicate RetainAI charge;</li>
          <li>an incorrect amount caused by a RetainAI billing error; or</li>
          <li>a verified service failure that materially prevented use of the paid service.</li>
        </ul>
        <p className="mb-6">Submit requests within 14 days of the charge. Approval is not guaranteed and does not limit non-waivable rights under applicable law. Approved refunds return to the original payment method; processing time depends on the financial institution.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">5. Billing help</h2>
        <p className="mb-6">Email <a href="mailto:owner@retainai.ca" className="text-yellow-300 underline">owner@retainai.ca</a> with the account email, charge date, and last four card digits. Never send a complete card number, password, or verification code.</p>

        <nav className="mt-12 text-sm text-gray-400 flex flex-wrap gap-4" aria-label="Legal pages">
          <a href="/privacy-policy" className="text-yellow-300 underline">Privacy Policy</a>
          <a href="/terms-of-service" className="text-yellow-300 underline">Terms of Service</a>
          <a href="/" className="text-yellow-300 underline">Return home</a>
        </nav>
      </main>
    </div>
  );
}
