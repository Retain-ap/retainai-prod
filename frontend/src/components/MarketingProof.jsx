import React from "react";
import proofContent from "../proofContent.json";

// Empty evidence stays out of the public page. See docs/HEYCATCH_EVIDENCE.md
// for the required source, permission and date before publishing a claim.
export function CustomerProof({ proof = proofContent }) {
  const quotes = proof.testimonials.filter((item) => item.approved === true &&
    item.name && item.quote && item.business && item.location && item.photo && item.source && item.approvedOn);
  if (!quotes.length) return null;
  return <section className="lp-section lp-customer-proof" aria-labelledby="customer-proof-title">
    <div className="lp-section-heading"><span>Customer experiences</span><h2 id="customer-proof-title">In their own words.</h2></div>
    <div className="lp-quote-grid">{quotes.map((quote) => <figure key={`${quote.name}-${quote.business}`}>
      <img src={quote.photo} alt={quote.name} width="64" height="64" loading="lazy" />
      <blockquote>{quote.quote}</blockquote><figcaption><strong>{quote.name}</strong><span>{quote.business} · {quote.location}</span></figcaption>
    </figure>)}</div>
  </section>;
}

export function SourcedProof({ proof = proofContent }) {
  const { usage, externalMention: mention } = proof;
  const showUsage = usage?.approved === true && usage.label && usage.source && usage.updatedOn && Number.isFinite(usage.count) && usage.count > 0;
  const showMention = mention?.approved === true && mention.title && mention.url?.startsWith("https://") && mention.publishedOn;
  if (!showUsage && !showMention) return null;
  return <aside className="lp-sourced-proof" aria-label="Verified RetainAI evidence">
    {showUsage && <p><strong>{usage.count.toLocaleString("en-CA")} {usage.label}</strong><span>Source: {usage.source}. Updated <time dateTime={usage.updatedOn}>{usage.updatedOn}</time>.</span></p>}
    {showMention && <p><a href={mention.url}>{mention.title}</a><span>Published <time dateTime={mention.publishedOn}>{mention.publishedOn}</time>.</span></p>}
  </aside>;
}

export function OwnerBlock({ proof = proofContent }) {
  const { owner } = proof;
  return <section className="lp-section lp-owner-section" id="owner" aria-labelledby="owner-title">
    {owner.photo && <img className="lp-owner-photo" src={owner.photo} alt={owner.name} width="240" height="240" loading="lazy" />}
    <div className="lp-section-heading"><span>A person you can reach</span><h2 id="owner-title">{owner.name}</h2>
      <p className="lp-owner-role">{owner.role}</p>
      {owner.whyBuilt && <p>{owner.whyBuilt}</p>}
      <p>Questions about setup, the product or your subscription? Contact Mateo directly at <a href={`mailto:${owner.email}`}>{owner.email}</a>.</p>
      {owner.profileUrl && <a className="lp-text-link" href={owner.profileUrl}>Meet Mateo</a>}
    </div>
  </section>;
}

export function ProductCapture({ proof = proofContent }) {
  const capture = proof.productCapture;
  if (!capture?.src || !capture.alt || !capture.capturedOn) return null;
  return <figure className="lp-product-capture">
    <a href={capture.src} aria-label="Open the RetainAI workspace screenshot at full size">
      <img src={capture.src} alt={capture.alt} width={capture.width} height={capture.height} loading="lazy" decoding="async" />
    </a>
    <figcaption><strong>Actual RetainAI workspace · example data</strong><span>Captured {capture.capturedOn}. Open the image to see the details.</span></figcaption>
  </figure>;
}
