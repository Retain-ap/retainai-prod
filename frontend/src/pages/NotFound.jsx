import React from "react";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-[#181a1b] text-gray-100">
      <main className="max-w-3xl mx-auto pt-16 pb-20 px-4">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-yellow-400 mb-3">Error 404</p>
        <h1 className="text-3xl md:text-4xl font-bold text-yellow-400 mb-3">Page not found</h1>
        <p className="mb-8">This page doesn't exist or has moved. Check the address, or continue from one of these pages.</p>

        <nav className="text-sm flex flex-wrap gap-4" aria-label="Helpful pages">
          <a href="/" className="text-yellow-300 underline">RetainAI home</a>
          <a href="/pricing" className="text-yellow-300 underline">Pricing</a>
          <a href="/signup" className="text-yellow-300 underline">Start your trial</a>
          <a href="/login" className="text-yellow-300 underline">Log in</a>
        </nav>
      </main>
    </div>
  );
}
