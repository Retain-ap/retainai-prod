import React from "react";
import { FaArrowRight, FaCheck, FaHeart } from "react-icons/fa";
import brandLogo from "../assets/logo.png";
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
            <p className="rp-eyebrow">The RetainAI partner pilot</p>
            <h1 id="partner-title">You help clients win customers.<br/><em>Help them keep them.</em></h1>
            <p className="rp-intro">Bring customer follow-up into the services you already offer. Introduce RetainAI to local businesses that need a clearer way to manage relationships, rebooking and the next conversation.</p>
            <div className="rp-actions"><a className="lp-primary-button" href="#partner-contact">Discuss a partnership <FaArrowRight aria-hidden="true" /></a><a className="rp-text-link" href="/#product">Explore the product <FaArrowRight aria-hidden="true" /></a></div>
            <p className="rp-caption">For agencies, business coaches and trusted advisors.</p>
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
            <p className="rp-example-note">A practical workflow to demonstrate—not a promise of bookings or revenue.</p>
          </aside>
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
          <div><p className="rp-eyebrow">Start with one good fit</p><h2 id="partner-process-title">A small pilot.<br/>A clear way forward.</h2><p>We’re exploring referral partnerships with people who understand the everyday needs of service businesses.</p><a className="rp-text-link" href="/#pricing">See current customer pricing <FaArrowRight aria-hidden="true" /></a></div>
          <ol>
            <li><h3>Tell us who you help.</h3><p>Share your business, public website and the types of clients you work with. No client list is needed.</p></li>
            <li><h3>Find a useful introduction.</h3><p>Discuss a real use case and how you would show RetainAI to a suitable business.</p></li>
            <li><h3>Agree the offer, then promote.</h3><p>For accepted partners, referral attribution, any commission, payout timing and refund rules are confirmed in writing before promotion begins.</p></li>
          </ol>
        </section>

        <section className="rp-section rp-faq" aria-labelledby="partner-faq-title">
          <div><p className="rp-eyebrow">Before you join</p><h2 id="partner-faq-title">Know what you’re recommending.</h2></div>
          <div>
            <details><summary>Is this a paid affiliate program?</summary><p>This is an invitation to discuss a referral partnership. Sending an enquiry does not enrol you, activate a referral link or create a commission agreement. Any paid arrangement is agreed separately with an accepted partner.</p></details>
            <details><summary>What could I earn?</summary><p>There is no standard commission rate advertised yet. We’ll agree the rate, qualifying payments, attribution window and payout conditions in writing before you start promoting.</p></details>
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
