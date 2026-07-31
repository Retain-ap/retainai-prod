import React, { useState } from "react";
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

const BOOKING_URL =
  "https://calendly.com/mateozufic1/retainai-setup-10-minutes?hide_gdpr_banner=1&primary_color=D6B25E";

const features = [
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

const useCases = [
  ["Salons & studios", "Turn first visits into repeat bookings with reminders and personal rebooking prompts."],
  ["Home services", "Keep estimates, scheduled visits, missed calls, and follow-ups from slipping through."],
  ["Coaches & consultants", "Nurture warm leads consistently while keeping every message personal."],
  ["Local service teams", "Give the whole team one clear customer history and a shared next action."],
];

const faqs = [
  [
    "What happens during the 14-day trial?",
    "You can set up your business profile, import contacts, connect supported integrations, and use the RetainAI workspace. Your billing and trial status remain visible inside the app.",
  ],
  [
    "Does RetainAI send messages without my approval?",
    "You control how messages are sent. AI drafts can be reviewed and edited, while automations show their triggers and actions before you activate them.",
  ],
  [
    "Can I use my existing WhatsApp Business account?",
    "Yes. RetainAI connects through Meta’s WhatsApp Business platform. Approved templates are used when a conversation is outside WhatsApp’s customer-service window.",
  ],
  [
    "Can I cancel or download my data?",
    "Yes. Billing controls, workspace export, and account-deletion controls are available in Settings. Account deletion includes a recovery window.",
  ],
  [
    "Is RetainAI only for large teams?",
    "No. It is designed for owner-led and growing service businesses that want a clear system without enterprise CRM complexity.",
  ],
  [
    "Will AI sound exactly like me?",
    "RetainAI uses your business context and tone preferences to prepare a useful draft. You can review and adjust the final message before sending.",
  ],
];

function AppPreview() {
  return (
    <div className="lp-preview" aria-label="RetainAI product preview">
      <div className="lp-preview-top">
        <div className="lp-window-dots"><i /><i /><i /></div>
        <span>Today’s retention briefing</span>
        <b><i /> Live</b>
      </div>
      <div className="lp-preview-grid">
        <aside className="lp-preview-sidebar">
          <div className="lp-mini-brand"><img src={brandLogo} alt="" /> RetainAI</div>
          {["Overview", "Contacts", "Calendar", "Messages", "Insights"].map((item, index) => (
            <span className={index === 0 ? "active" : ""} key={item}>{item}</span>
          ))}
        </aside>
        <div className="lp-preview-main">
          <div className="lp-preview-heading">
            <div><small>GOOD MORNING</small><strong>Your relationships, prioritized.</strong></div>
            <button type="button">Open actions</button>
          </div>
          <div className="lp-preview-stats">
            <div><small>Needs attention</small><strong>4</strong><span>Review today</span></div>
            <div><small>Ready to rebook</small><strong>7</strong><span>Warm opportunities</span></div>
            <div><small>Upcoming</small><strong>5</strong><span>Next 7 days</span></div>
          </div>
          <div className="lp-preview-lower">
            <div className="lp-priority-card">
              <div className="lp-card-title"><span>Priority queue</span><small>Next best action</small></div>
              {[
                ["MP", "Maya P.", "Waiting on reply", "Send follow-up"],
                ["JR", "Jordan R.", "Ready to rebook", "Offer a time"],
                ["AL", "Alex L.", "Visit tomorrow", "Confirm"],
              ].map(([initials, name, status, action]) => (
                <div className="lp-priority-row" key={name}>
                  <i>{initials}</i><span><b>{name}</b><small>{status}</small></span><button type="button">{action}</button>
                </div>
              ))}
            </div>
            <div className="lp-ai-card">
              <span><FaMagic /> AI briefing</span>
              <strong>Start with Maya.</strong>
              <p>Her last message showed clear interest. A short, personal check-in is the strongest next move.</p>
              <div>Draft ready <FaArrowRight /></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function FAQItem({ question, answer, open, onClick }) {
  return (
    <div className={`lp-faq-item ${open ? "open" : ""}`}>
      <button type="button" onClick={onClick} aria-expanded={open}>
        <span>{question}</span><FaChevronDown />
      </button>
      {open && <p>{answer}</p>}
    </div>
  );
}

export default function LandingPage() {
  const [openFaq, setOpenFaq] = useState(0);

  const bookDemo = () => {
    if (window.Calendly?.initPopupWidget) {
      window.Calendly.initPopupWidget({ url: BOOKING_URL });
    } else {
      window.open(BOOKING_URL, "_blank", "noopener,noreferrer");
    }
  };

  return (
    <div className="lp-page">
      <a className="lp-skip" href="#main-content">Skip to content</a>
      <nav className="lp-nav" aria-label="Main navigation">
        <a className="lp-brand" href="/" aria-label="RetainAI home">
          <img src={brandLogo} alt="" /><span>RetainAI</span>
        </a>
        <div className="lp-nav-links">
          <a href="#product">Product</a>
          <a href="#how-it-works">How it works</a>
          <a href="#pricing">Pricing</a>
          <a href="#faq">FAQ</a>
        </div>
        <div className="lp-nav-actions">
          <a className="lp-link-button" href="/login">Log in</a>
          <a className="lp-primary-button small" href="/signup">Start free trial <FaArrowRight /></a>
        </div>
      </nav>

      <main id="main-content">
        <section className="lp-hero">
          <div className="lp-glow one" /><div className="lp-glow two" />
          <div className="lp-hero-copy">
            <div className="lp-kicker"><span><FaWhatsapp /></span> Built for relationship-driven businesses</div>
            <h1>Keep more customers.<br /><em>Miss fewer moments.</em></h1>
            <p>
              RetainAI brings customer conversations, follow-ups, appointments,
              invoices, and retention priorities into one calm workspace.
            </p>
            <div className="lp-hero-actions">
              <a className="lp-primary-button" href="/signup">Start your 14-day trial <FaArrowRight /></a>
              <button className="lp-secondary-button" type="button" onClick={bookDemo}>Book a 10-minute walkthrough</button>
            </div>
            <div className="lp-trust-row">
              <span><FaCheck /> Guided setup</span>
              <span><FaCheck /> Clear billing controls</span>
              <span><FaCheck /> Export your data</span>
              <span><FaCheck /> Cancel anytime</span>
            </div>
          </div>
          <AppPreview />
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
          <div className="lp-feature-grid">
            {features.map((feature) => (
              <article key={feature.title}>
                <i>{feature.icon}</i><h3>{feature.title}</h3><p>{feature.copy}</p>
              </article>
            ))}
          </div>
        </section>

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
          <div className="lp-pricing-card">
            <div className="lp-price-copy">
              <small>RETAINAI STANDARD</small>
              <h3>One complete customer-retention workspace.</h3>
              <p>Contacts, conversations, appointments, insights, automations, invoices, team tools, and owner controls.</p>
              <div className="lp-price"><strong>$30</strong><span>CAD<br />per month</span></div>
              <p className="lp-launch-note">Launch pricing may be available during checkout.</p>
            </div>
            <div className="lp-price-actions">
              <ul>
                {["14-day trial", "Guided onboarding", "WhatsApp Business connection", "AI-assisted messaging", "Retention insights", "Cancel and export controls"].map((item) => (
                  <li key={item}><FaCheck /> {item}</li>
                ))}
              </ul>
              <a className="lp-primary-button" href="/signup">Start your trial <FaArrowRight /></a>
              <small>Payment method required. Subscription begins after the trial unless cancelled.</small>
            </div>
          </div>
        </section>

        <section className="lp-section lp-faq-section" id="faq">
          <div className="lp-faq-heading">
            <span>Questions, answered</span>
            <h2>Know exactly what you’re signing up for.</h2>
            <p>Clear expectations create better customer relationships—including ours.</p>
            <button type="button" onClick={bookDemo}>Still unsure? Book a walkthrough <FaArrowRight /></button>
          </div>
          <div className="lp-faq-list">
            {faqs.map(([question, answer], index) => (
              <FAQItem
                key={question}
                question={question}
                answer={answer}
                open={openFaq === index}
                onClick={() => setOpenFaq(openFaq === index ? -1 : index)}
              />
            ))}
          </div>
        </section>

        <section className="lp-final-cta">
          <div>
            <span><FaRegBell /> Your next best customer action is waiting.</span>
            <h2>Build a business customers remember.</h2>
            <p>Start organizing the relationships you already worked hard to earn.</p>
          </div>
          <div>
            <a className="lp-primary-button" href="/signup">Start your 14-day trial <FaArrowRight /></a>
            <button type="button" onClick={bookDemo}>Book a walkthrough</button>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-footer-brand"><img src={brandLogo} alt="" /><span><b>RetainAI</b><small>Client relationships. Done right.</small></span></div>
        <div><a href="#product">Product</a><a href="#pricing">Pricing</a><a href="/login">Log in</a></div>
        <div><a href="/privacy-policy">Privacy</a><a href="/terms-of-service">Terms</a><a href={`mailto:support@retainai.ca`}>Support</a></div>
        <small>© {new Date().getFullYear()} RetainAI. All rights reserved.</small>
      </footer>
    </div>
  );
}
