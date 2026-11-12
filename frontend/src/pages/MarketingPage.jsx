import React from "react";
import { FaArrowRight } from "react-icons/fa";
import publicContent from "../publicContent.json";
import { BOOKING_URL, FAQSection, features, MarketingFooter, MarketingNav, PricingCard, useCases } from "../components/LandingPage";
import { CustomerProof, OwnerBlock, ProductCapture, SourcedProof } from "../components/MarketingProof";

export default function MarketingPage({ path }) {
  const page = publicContent.pages[path];
  const category = path === "/retention-crm-for-service-businesses";
  return <div className="lp-page">
    <a className="lp-skip" href="#main-content">Skip to content</a>
    <MarketingNav />
    <main id="main-content">
      <header className="lp-section lp-route-hero">
        <div className="lp-section-heading"><span>{page.eyebrow}</span><h1>{page.heading}</h1><p>{page.intro}</p></div>
        <div className="lp-route-actions"><a className="lp-primary-button" href="/signup">Start your 14-day trial <FaArrowRight /></a><a className="lp-secondary-button" href={BOOKING_URL}>Book a 10-minute walkthrough</a></div>
      </header>
      {page.sections.length > 0 && <div className="lp-section lp-route-sections">{page.sections.map((section) => <section key={section.heading}><h2>{section.heading}</h2><p>{section.copy}</p></section>)}</div>}
      {path === "/about" && <OwnerBlock />}
      {path === "/features" && <section className="lp-section lp-feature-section"><div className="lp-section-heading"><span>One relationship workspace</span><h2>Keep the work connected.</h2></div><div className="lp-feature-grid">{features.map((feature) => <article key={feature.title}><i>{feature.icon}</i><h3>{feature.title}</h3><p>{feature.copy}</p></article>)}</div><ProductCapture /></section>}
      {(path === "/customers" || category) && <section className="lp-section lp-route-use-cases"><div className="lp-section-heading"><span>Designed around repeat business</span><h2>Find your day-to-day work.</h2></div><div className="lp-use-list">{useCases.map(([title, copy], index) => <article key={title}><b>0{index + 1}</b><span><h3>{title}</h3><p>{copy}</p></span></article>)}</div></section>}
      {path === "/customers" && <><CustomerProof /><SourcedProof /></>}
      {(path === "/pricing" || category) && <section className="lp-section lp-pricing-section"><h2 className="lp-route-price-title">One plan. The full workspace.</h2><PricingCard /></section>}
      {path === "/pricing" && <FAQSection />}
      <nav className="lp-section lp-related-pages" aria-label="Explore RetainAI"><a href="/features">Explore the features <FaArrowRight /></a><a href="/pricing">See pricing and trial terms <FaArrowRight /></a><a href="/about">Meet the owner <FaArrowRight /></a><a href="/retention-crm-for-service-businesses">Retention CRM for service businesses <FaArrowRight /></a><a href="/find-customers-who-stopped-rebooking">Guide: find customers who stopped rebooking <FaArrowRight /></a></nav>
    </main>
    <MarketingFooter />
  </div>;
}
