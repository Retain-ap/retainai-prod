import React from "react";
import {
  FaArrowRight,
  FaBolt,
  FaCalendarCheck,
  FaCheck,
  FaChevronDown,
  FaClock,
  FaComments,
  FaFileInvoiceDollar,
  FaHeart,
  FaMagic,
  FaRegBell,
  FaShieldAlt,
  FaWhatsapp,
} from "react-icons/fa";
import brandLogo from "../assets/logo.png";
import "./LandingPage.css";
import publicContent from "../publicContent.json";
import { CustomerProof, OwnerBlock, ProductCapture, SourcedProof } from "./MarketingProof";

export const BOOKING_URL = publicContent.bookingUrl;

export const features = [
  {
    icon: <FaWhatsapp />,
    title: "One WhatsApp inbox",
    copy: "See customer conversations, replies, and context without jumping between tools.",
  },
  {
    icon: <FaMagic />,
    title: "AI that uses context",
    copy: "Draft thoughtful replies using the customer’s history, tags, and your preferred tone.",
  },
  {
    icon: <FaHeart />,
    title: "Retention priorities",
    copy: "Know who needs attention, who is ready to rebook, and what to do next.",
  },
  {
    icon: <FaCalendarCheck />,
    title: "Appointments together",
    copy: "Keep bookings, reminders, customer records, and follow-up actions connected.",
  },
  {
    icon: <FaBolt />,
    title: "Reliable playbooks",
    copy: "Build win-back, reminder, review, and no-response workflows with visible controls.",
  },
  {
    icon: <FaFileInvoiceDollar />,
    title: "Revenue follow-through",
    copy: "Create invoices, track payment status, and follow up from the same customer view.",
  },
];

export const useCases = [
  ["Salons & studios", "Turn first visits into repeat bookings with reminders and personal rebooking prompts."],
  ["Home services", "Keep estimates, scheduled visits, missed calls, and follow-ups from slipping through."],
  ["Coaches & consultants", "Nurture warm leads consistently while keeping every message personal."],
  ["Local service teams", "Give the whole team one clear customer history and a shared next action."],
];

export const faqs = publicContent.faqs;

export function FAQSection() {
  return <section className="lp-section lp-faq-section" id="faq">
    <div className="lp-faq-heading">
      <span>Questions, answered</span><h2>Know exactly what you’re signing up for.</h2>
      <p>Clear expectations create better customer relationships—including ours.</p>
      <a href={BOOKING_URL}>Still unsure? Book a walkthrough <FaArrowRight /></a>
    </div>
    <div className="lp-faq-list">{faqs.map(([question, answer], index) => (
      <details className="lp-faq-item" key={question} aria-label={question} open={index === 0}>
        <summary><span>{question}</span><FaChevronDown /></summary><p>{answer}</p>
      </details>
    ))}</div>
  </section>;
}

export default function LandingPage() {
  return (
    <div className="lp-page">
      <a className="lp-skip" href="#main-content">Skip to content</a>
      <MarketingNav home />

      <main id="main-content">
        <section className="lp-hero">
          <div className="lp-glow one" /><div className="lp-glow two" />
          <div className="lp-hero-copy">
            <div className="lp-kicker"><span><FaWhatsapp /></span> The customer retention CRM for Canadian service businesses</div>
            <h1>Keep more customers.<br /><em>Miss fewer moments.</em></h1>
            <p>
              RetainAI brings customer conversations, follow-ups, appointments,
              invoices, and retention priorities into one calm workspace.
            </p>
            <div className="lp-hero-actions">
              <a className="lp-primary-button" href="/signup">Start your 14-day trial <FaArrowRight /></a>
              <a className="lp-secondary-button" href={BOOKING_URL}>Book a 10-minute walkthrough</a>
            </div>
            <div className="lp-trust-row">
              <span><FaCheck /> Guided setup</span>
              <span><FaCheck /> Clear billing controls</span>
              <span><FaCheck /> Export your data</span>
              <span><FaCheck /> Cancel anytime</span>
            </div>
          </div>
          <ProductCapture />
          <SourcedProof />
        </section>

        <section className="lp-value-strip" aria-label="RetainAI value">
          <div><FaComments /><span><b>One customer history</b><small>Conversations and context together</small></span></div>
          <div><FaClock /><span><b>A clear next action</b><small>Priorities instead of dashboard noise</small></span></div>
          <div><FaShieldAlt /><span><b>You stay in control</b><small>Review, edit, export, or cancel</small></span></div>
        </section>

        <section className="lp-section lp-problem">
          <div className="lp-section-heading">
            <span>The problem RetainAI solves</span>
            <h2>Your next sale is often already in your customer list.</h2>
            <p>But customer context gets scattered across inboxes, calendars, notes, and memory.</p>
          </div>
          <div className="lp-problem-grid">
            <div className="before">
              <small>WITHOUT A SYSTEM</small>
              <h3>Important moments get buried.</h3>
              <ul>
                <li>Follow-ups depend on memory</li>
                <li>Customer replies lack context</li>
                <li>Rebooking opportunities go unnoticed</li>
                <li>Tools show activity, not priority</li>
              </ul>
            </div>
            <div className="after">
              <small>WITH RETAINAI</small>
              <h3>Every relationship has a next step.</h3>
              <ul>
                <li><FaCheck /> One organized customer timeline</li>
                <li><FaCheck /> AI-assisted replies with context</li>
                <li><FaCheck /> Visible retention and rebooking cues</li>
                <li><FaCheck /> Clear actions for you and your team</li>
              </ul>
            </div>
          </div>
        </section>

        <section className="lp-section" id="how-it-works">
          <div className="lp-section-heading centered">
            <span>Simple on the surface</span>
            <h2>From scattered follow-up to a daily rhythm.</h2>
          </div>
          <div className="lp-steps">
            {[
              ["01", "Bring in your customers", "Import contacts and keep their details, tags, notes, and activity together."],
              ["02", "Connect the work", "Link WhatsApp, calendar, and billing tools when they are relevant to your workflow."],
              ["03", "Act on what matters", "Use the briefing, inbox, and playbooks to follow up with clarity and consistency."],
            ].map(([number, title, copy]) => (
              <article key={number}><b>{number}</b><h3>{title}</h3><p>{copy}</p></article>
            ))}
          </div>
        </section>

        <section className="lp-section lp-feature-section" id="product">
          <div className="lp-section-heading centered">
            <span>One relationship workspace</span>
            <h2>Everything needed to turn attention into retention.</h2>
            <p>No bloated enterprise setup. No mystery automation. Just the context and controls your business needs.</p>
          </div>
          <p className="lp-calm-note">Start the day knowing which regulars need attention, with a next step you can act on.</p>
          <div className="lp-feature-grid">
            {features.map((feature) => (
              <article key={feature.title}>
                <i>{feature.icon}</i><h3>{feature.title}</h3><p>{feature.copy}</p>
              </article>
            ))}
          </div>
        </section>

        <CustomerProof />

        <section className="lp-section lp-use-cases">
          <div className="lp-use-copy">
            <span>Designed around repeat business</span>
            <h2>Built for owners who win through trust.</h2>
            <p>RetainAI is most useful where relationships, responsiveness, and repeat visits drive growth.</p>
            <a href="/signup">See RetainAI with your workflow <FaArrowRight /></a>
          </div>
          <div className="lp-use-list">
            {useCases.map(([title, copy], index) => (
              <article key={title}><b>0{index + 1}</b><span><h3>{title}</h3><p>{copy}</p></span></article>
            ))}
          </div>
        </section>

        <section className="lp-section lp-pricing-section" id="pricing">
          <div className="lp-section-heading centered">
            <span>Transparent pricing</span>
            <h2>Start small. Keep the full system.</h2>
            <p>Explore the workflow during your trial, then choose whether RetainAI belongs in your business.</p>
          </div>
          <PricingCard />
        </section>

        <OwnerBlock />
        <FAQSection />

        <section className="lp-final-cta">
          <div>
            <span><FaRegBell /> Your next best customer action is waiting.</span>
            <h2>Build a business customers remember.</h2>
            <p>Start organizing the relationships you already worked hard to earn.</p>
          </div>
          <div>
            <a className="lp-primary-button" href="/signup">Start your 14-day trial <FaArrowRight /></a>
            <a href={BOOKING_URL}>Book a walkthrough</a>
          </div>
        </section>
      </main>

      <MarketingFooter />
    </div>
  );
}

export function MarketingNav({ home = false }) {
  return (<nav className="lp-nav" aria-label="Main navigation">
        <a className="lp-brand" href="/" aria-label="RetainAI home">
          <img src={brandLogo} alt="RetainAI logo" /><span>RetainAI</span>
        </a>
        <details className="lp-mobile-menu"><summary>Explore</summary><div><a href="/#product">Product</a><a href="/#how-it-works">How it works</a><a href="/#pricing">Pricing</a><a href="/#faq">FAQ</a><a href="/retention-crm-for-service-businesses">Who it’s for</a><a href="/about">About</a></div></details>
        <div className="lp-nav-links">
          <a href={`${home ? "" : "/"}#product`}>Product</a>
          <a href={`${home ? "" : "/"}#how-it-works`}>How it works</a>
          <a href={`${home ? "" : "/"}#pricing`}>Pricing</a>
          <a href={`${home ? "" : "/"}#faq`}>FAQ</a>
          <a href="/retention-crm-for-service-businesses">Who it’s for</a>
        </div>
        <div className="lp-nav-actions">
          <a className="lp-link-button" href="/login">Log in</a>
          <a className="lp-primary-button small" href="/signup">Start free trial <FaArrowRight /></a>
        </div>
      </nav>);
}

export function MarketingFooter() {
  return (<footer className="lp-footer">
        <div className="lp-footer-brand"><img src={brandLogo} alt="RetainAI logo" /><span><b>RetainAI</b><small>Mateo Zufic · Owner, RetainAI</small></span></div>
        <div><a href="/#product">Product</a><a href="/#pricing">Pricing</a><a href="/about">About Mateo &amp; RetainAI</a><a href="/customers">Who it’s for</a><a href="/retention-crm-for-service-businesses">Service business CRM</a><a href="/find-customers-who-stopped-rebooking">Rebooking guide</a><a href="/partners">Partner with RetainAI</a><a href="/login">Log in</a></div>
        <div><a href="/privacy-policy">Privacy</a><a href="/terms-of-service">Terms</a><a href="/refund-policy">Refunds &amp; cancellations</a><a href={`mailto:owner@retainai.ca`}>Support</a></div>
        <small>© {new Date().getFullYear()} RetainAI. All rights reserved.</small>
      </footer>);
}

export function PricingCard() {
  return (<div className="lp-pricing-card">
            <div className="lp-price-copy">
              <small>RETAINAI STANDARD</small>
              <h3>One complete customer-retention workspace.</h3>
              <p>Contacts, conversations, appointments, insights, automations, invoices, team tools, and owner controls.</p>
              <div className="lp-price"><strong>$20</strong><span>CAD<br />per month</span></div>
              <p className="lp-price-anchor">Less than C$1 a day for RetainAI, billed C$20 monthly.</p>
              <p className="lp-launch-note">One monthly plan, no annual commitment or separate feature tiers. Taxes and any connected-service charges are separate. Confirm your total at checkout.</p>
            </div>
            <div className="lp-price-actions">
              <ul>
                {["14-day trial", "Guided onboarding", "WhatsApp Business connection", "AI-assisted messaging", "Retention insights", "Cancel and export controls"].map((item) => (
                  <li key={item}><FaCheck /> {item}</li>
                ))}
              </ul>
              <a className="lp-primary-button" href="/signup">Start your trial <FaArrowRight /></a>
              <p className="lp-payment-reassurance">Paid by card through Stripe. Cancel anytime, export your data.</p>
              <small>Payment method required. Subscription begins after the trial unless cancelled.</small>
            </div>
          </div>);
}
