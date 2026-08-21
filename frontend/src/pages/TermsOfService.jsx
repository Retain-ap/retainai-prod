// src/pages/TermsOfService.jsx
import React from "react";

export default function TermsOfService() {
  return (
    <div className="min-h-screen bg-[#181a1b] text-gray-100">
      <div className="max-w-3xl mx-auto pt-16 pb-20 px-4">
        <h1 className="text-3xl md:text-4xl font-bold text-yellow-400 mb-7">Terms of Service</h1>

        <p className="text-sm text-gray-400 mb-8">
          Effective August 21, 2026
        </p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">1. Acceptance of Terms</h2>
        <p className="mb-6">
          By using RetainAI, you agree to these Terms of Service and our{" "}
          <a href="/privacy-policy" className="text-yellow-300 underline">Privacy Policy</a>.
        </p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">2. Use of Service</h2>
        <ul className="list-disc ml-6 mb-6 space-y-2">
          <li>You must provide accurate registration information.</li>
          <li>You are responsible for all activity on your account.</li>
          <li>Do not use RetainAI for unlawful, abusive, or harmful purposes.</li>
          <li>Do not send spam, impersonate others, bypass consent requirements, upload malicious code, probe the Service, or use it to make unlawful high-impact decisions.</li>
          <li>You are responsible for your contact data, message content, customer notices, and compliance with applicable privacy, telemarketing, anti-spam, and messaging-platform rules.</li>
        </ul>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">3. Payment & Subscription</h2>
        <ul className="list-disc ml-6 mb-6 space-y-2">
          <li>Plans are billed at the price, currency, taxes, and interval displayed at checkout.</li>
          <li>Eligible new customers receive the trial period displayed at checkout; a payment method may be required.</li>
          <li>Cancel anytime from your dashboard; cancellations take effect at the end of the current billing cycle.</li>
          <li>Trials, renewals, refunds, and billing corrections are governed by our <a href="/refund-policy" className="text-yellow-300 underline">Refund &amp; Cancellation Policy</a>.</li>
        </ul>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">4. AI-Assisted Features</h2>
        <p className="mb-6">RetainAI may generate drafts, summaries, scores, or recommendations. AI output can be incomplete or incorrect and is not professional advice. You must review output before sending or acting on it and remain responsible for customer communications and business decisions.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">5. Data & Privacy</h2>
        <p className="mb-6">
          We handle your data according to our{" "}
          <a href="/privacy-policy" className="text-yellow-300 underline">Privacy Policy</a>.
        </p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">6. Connected Services</h2>
        <p className="mb-6">Optional integrations are also governed by their providers, including Meta/WhatsApp, Google, Stripe, and SendGrid. RetainAI is not responsible for third-party outages, policy changes, suspensions, or actions outside our control.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">7. Service Availability</h2>
        <ul className="list-disc ml-6 mb-6 space-y-2">
          <li>We strive for high uptime but service may be interrupted for maintenance or unforeseen events.</li>
          <li>RetainAI is not liable for losses resulting from service interruptions.</li>
        </ul>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">8. Account Suspension, Cancellation & Deletion</h2>
        <ul className="list-disc ml-6 mb-6 space-y-2">
          <li>We may suspend or terminate accounts that violate these terms or abuse the service.</li>
          <li>You may export or delete workspace data using available account controls, subject to identity verification, backup rotation, legal retention, and any displayed recovery period.</li>
          <li>Deleting a workspace is separate from cancelling a subscription; confirm billing status before deletion.</li>
        </ul>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">9. Intellectual Property</h2>
        <p className="mb-6">RetainAI and its software, branding, and original content remain our property. You retain ownership of content you submit and grant RetainAI the limited rights needed to host, process, transmit, and protect it while providing the Service.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">10. Disclaimers & Liability</h2>
        <p className="mb-6">To the maximum extent permitted by law, the Service is provided “as is” and “as available.” RetainAI does not guarantee particular revenue, retention, delivery, or AI results. Nothing in these Terms excludes liability or consumer rights that cannot legally be excluded. Any additional limitation, indemnity, or governing-law wording should be confirmed by qualified counsel for your jurisdiction.</p>

        <h2 className="text-2xl font-bold text-yellow-300 mt-8 mb-2">11. Updates to Terms</h2>
        <p className="mb-6">
          These Terms may be updated periodically. We will notify users of significant changes via email or in-app notices.
        </p>

        <div className="mt-12 text-gray-400 text-sm pb-10">
          Questions? Email{" "}
          <a href="mailto:owner@retainai.ca" className="text-yellow-300 underline">
            owner@retainai.ca
          </a>
        </div>
      </div>
    </div>
  );
}
