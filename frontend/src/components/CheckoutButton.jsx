// src/components/CheckoutButton.jsx
import React from "react";
import { loadStripe } from "@stripe/stripe-js";

// ⬇️ Use your live publishable key
const publishableKey = process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY || "";
const stripePromise = publishableKey ? loadStripe(publishableKey) : Promise.resolve(null);

export default function CheckoutButton({ priceId, children }) {
  const handleCheckout = async () => {
    const stripe = await stripePromise;
    if (!stripe) {
      alert("Payments are temporarily unavailable. Please contact RetainAI support.");
      return;
    }
    const { error } = await stripe.redirectToCheckout({
      lineItems: [{ price: priceId, quantity: 1 }],
      mode: "subscription",
      successUrl: window.location.origin + "/login?success=true",
      cancelUrl: window.location.origin + "/",
    });
    if (error) alert(error.message);
  };

  return (
    <button
      className="bg-yellow-400 text-black px-6 py-3 rounded-xl font-bold shadow-lg hover:bg-yellow-300 transition block text-center"
      onClick={handleCheckout}
    >
      {children || "Start Free Trial"}
    </button>
  );
}
