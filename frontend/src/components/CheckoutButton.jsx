import React from "react";

// Checkout creation belongs to the backend, where RetainAI verifies existing
// subscriptions and applies Stripe idempotency protection. This reusable CTA
// therefore starts the guarded signup flow instead of creating a subscription
// directly in the browser.
export default function CheckoutButton({ children }) {
  return (
    <button
      className="bg-yellow-400 text-black px-6 py-3 rounded-xl font-bold shadow-lg hover:bg-yellow-300 transition block text-center"
      onClick={() => window.location.assign("/signup")}
    >
      {children || "Start Free Trial"}
    </button>
  );
}
