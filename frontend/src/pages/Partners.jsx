import React from "react";
import { FaArrowRight, FaCheck, FaHeart } from "react-icons/fa";
import brandLogo from "../assets/logo.png";
import publicContent from "../publicContent.json";
import "../components/LandingPage.css";
import "./Partners.css";

const enquiry = `mailto:owner@retainai.ca?subject=${encodeURIComponent("RetainAI partnership enquiry")}&body=${encodeURIComponent("Hi RetainAI,\n\nI’m interested in a partnership.\n\nName and business:\nWebsite or public profile:\nTypes of businesses I work with:\nHow I’d introduce RetainAI:\n\nThank you!")}`;

export default function Partners() {
  return (
    <div className="lp-page rp-page">
      <a className="lp-skip" href="#partner-main">Skip to content</a>
      <header className="lp-nav">
        <a className="lp-brand" href="/" aria-label="RetainAI home"><img src={brandLogo} alt="" /><span>RetainAI</span></a>
        <nav className="lp-nav-links" aria-label="Main navigation"><a href="/#product">Product</a><a href="/#pricing">Pricing</a><a href="#how-it-works">How it works</a></nav>
        <a className="lp-primary-button small" href="#partner-contact">Become a partner <FaArrowRight aria-hidden="true" /></a>
      </header>
      <main id="partner-main" tabIndex={-1}>
        <section className="rp-hero" aria-labelledby="partner-title">
          <div>
            <p className="rp-eyebrow">RetainAI referral partners · 30% commission</p>
            <h1 id="partner-title">Help your clients<br/><em>keep more customers.</em></h1>
            <p className="rp-intro">Bring customer follow-up into the services you already offer. Introduce RetainAI to local businesses that need a clearer way to manage relationships, rebooking and the next conversation.</p>
            <div className="rp-actions"><a className="lp-primary-button" href="#partner-contact">Discuss a partnership <FaArrowRight aria-hidden="true" /></a><a className="rp-text-link" href="/#product">Explore the product <FaArrowRight aria-hidden="true" /></a></div>
            <p className="rp-caption">Earn 30% for the first 12 months of each qualifying referral. For agencies, business coaches and trusted advisors.</p>
          </div>
          <aside className="rp-example" aria-label="Illustrative salon workflow">
            <div className="rp-example-heading"><span><FaHeart aria-hidden="true" /> A reason to return</span><small>Example workflow</small></div>
            <h2>A great first visit.<br/>What happens next?</h2>
            <p>A salon owner wants to follow up with guests who haven’t booked again.</p>
            <ol>
              <li><span>01</span><div><h3>Find the next conversation.</h3><p>Review customer history and follow-up priorities.</p></div></li>
              <li><span>02</span><div><h3>Make the message personal.</h3><p>Review and edit an AI-assisted draft before sending.</p></div></li>
              <li><span>03</span><div><h3>Keep the next step visible.</h3><p>Track the reply, appointment or follow-up in one workspace.</p></div></li>
            </ol>
          </aside>
        </section>

        <section className="rp-section rp-today" aria-labelledby="partner-today-title">
          <p className="rp-eyebrow">Live in RetainAI now</p>
          <h2 id="partner-today-title">What your clients get today.</h2>
          <ul className="rp-benefits">{publicContent.partners.benefits.map((item) => <li key={item}><FaCheck aria-hidden="true" /> {item}</li>)}</ul>
          <p className="rp-terms">{publicContent.partners.terms}</p>
        </section>

        <section className="rp-section" aria-labelledby="partner-fit-title">
          <p className="rp-eyebrow">Make retention part of your offer</p>
          <h2 id="partner-fit-title">A useful next step<br/>for the clients you already serve.</h2>
          <div className="rp-cards">
            <article><span>Marketing agencies</span><h3>Keep the conversation going after the campaign.</h3><p>Introduce a follow-up workspace alongside the leads and attention you help generate.</p></article>
            <article><span>Business coaches</span><h3>Turn good advice into a daily routine.</h3><p>Help owners build a repeatable habit around customer history, rebooking and timely replies.</p></article>
            <article><span>Consultants &amp; advisors</span><h3>Recommend a system for the next step.</h3><p>Connect clients with a practical place for contacts, appointments, invoices and follow-up.</p></article>
          </div>
        </section>

        <section className="rp-process rp-section" id="how-it-works" aria-labelledby="partner-process-title">
          <div><p className="rp-eyebrow">Start with one good fit</p><h2 id="partner-process-title">A small pilot.<br/>A clear way forward.</h2><p>We’re welcoming referral partners who understand the everyday needs of service businesses.</p><a className="rp-text-link" href="/#pricing">See current customer pricing <FaArrowRight aria-hidden="true" /></a></div>
          <ol>
            <li><h3>Tell us who you help.</h3><p>Share your business, public website and the types of clients you work with. No client list is needed.</p></li>
            <li><h3>Find a useful introduction.</h3><p>Discuss a real use case and how you would show RetainAI to a suitable business.</p></li>
            <li><h3>Agree the offer, then promote.</h3><p>Accepted partners receive a tracked link and written terms: 30% of qualifying membership payments for 12 months, with clear attribution and refund rules.</p></li>
          </ol>
        </section>

        <section className="rp-section rp-faq" aria-labelledby="partner-faq-title">
          <div><p className="rp-eyebrow">Before you join</p><h2 id="partner-faq-title">Know what you’re recommending.</h2></div>
          <div>
            <details><summary>Is this a paid affiliate program?</summary><p>Yes. Approved partners earn 30% of qualifying membership payments for the first 12 months. Apply below; we confirm the partnership and activate your personal link after written acceptance. An enquiry alone does not enrol you.</p></details>
            <details><summary>What could I earn?</summary><p>Earn 30% of qualifying base membership payments for 12 months from a referred customer’s first successful payment. Commission is calculated after discounts, before tax; add-ons, free trials and unpaid invoices do not earn commission. Refunds reduce commission and disputes put it on hold. At the current CA$20 monthly base price, a full-price payment earns CA$6 before any later refund adjustment.</p></details>
            <details><summary>How are referrals tracked?</summary><p>Your approved link credits the first valid referral for a new account created within 60 days on the same browser. Existing accounts, self-referrals and duplicate accounts are excluded. Clearing cookies or changing browsers can prevent attribution. The 12-month window does not restart after cancellation or rejoining.</p></details>
            <details><summary>When are commissions paid?</summary><p>Commissions have a 30-day hold and are reviewed monthly. We reconcile payments and refunds before paying; later refunds are deducted from future balances. Accepted partners confirm payment details in writing. No purchase is needed to apply, and earnings are not guaranteed.</p></details>
            <details><summary>What should I show a potential customer?</summary><p>Start with one follow-up they struggle to keep track of. Show how customer history, an editable message draft and a visible next action fit that workflow. Use demo data or information the business has agreed to share. <a href="/#product">See the product overview.</a></p></details>
            <details><summary>Can I explore it before recommending it?</summary><p>Yes. Review the <a href="/#product">product overview</a> and <a href="/#pricing">current pricing and trial terms</a>, or email us about your use case before signing up. A paid account is not required to enquire about a partnership.</p></details>
            <details><summary>How should I explain the partnership?</summary><p>Clearly disclose any payment, free access or other benefit alongside your recommendation. Use your honest experience and avoid guarantees about revenue, bookings or customer results.</p></details>
          </div>
        </section>

        <section className="rp-contact" id="partner-contact" aria-labelledby="partner-contact-title">
          <div><p className="rp-eyebrow">Let’s build a useful introduction</p><h2 id="partner-contact-title">Who could you help<br/>follow up better?</h2><p>Tell us about your business and the clients you support. We’ll explore whether a partnership is a good fit.</p><ul><li><FaCheck aria-hidden="true" /> Start with your existing expertise</li><li><FaCheck aria-hidden="true" /> Agree the terms before you promote</li><li><FaCheck aria-hidden="true" /> Keep the recommendation honest</li></ul></div>
          <div className="rp-contact-action"><a className="lp-primary-button" href={enquiry}>Email your interest <FaArrowRight aria-hidden="true" /></a><p>Opens a draft in your email app for you to review and send.</p><p>Or write to <a href="mailto:owner@retainai.ca">owner@retainai.ca</a>.</p><p>Share public work links only; please leave out client records and private account details. <a href="/privacy-policy">Privacy policy</a></p></div>
        </section>
      </main>
      <footer className="lp-footer">
        <div className="lp-footer-brand"><img src={brandLogo} alt="" /><span><b>RetainAI</b><small>Client relationships. Done right.</small></span></div>
        <nav aria-label="Product and partners"><a href="/">Home</a><a href="/#pricing">Pricing</a><a href="/partners" aria-current="page">Partner with RetainAI</a></nav>
        <nav aria-label="Legal and support"><a href="/privacy-policy">Privacy</a><a href="/terms-of-service">Terms</a><a href="/refund-policy">Refunds &amp; cancellations</a><a href="mailto:owner@retainai.ca">Support</a></nav>
        <small>© {new Date().getFullYear()} RetainAI. All rights reserved.</small>
      </footer>
    </div>
  );
}
