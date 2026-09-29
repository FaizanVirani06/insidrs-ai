const sections = [
  {
    title: "Information we collect",
    body: [
      "Account information, including username, contact email, password hash, role, subscription status, and account settings.",
      "Profile and preference information you choose to save, such as sectors, ticker interests, alert preferences, and minimum signal settings.",
      "Billing and subscription identifiers from Stripe, such as customer IDs, subscription IDs, plan status, and renewal dates. We do not store full card numbers.",
      "Product usage information needed to operate and secure the service, including authentication cookies, session events, feedback, support messages, and administrative activity.",
      "Content generated or submitted through the service, including watchlists, support chats, feedback, and social-post drafts created by administrators.",
    ],
  },
  {
    title: "How we use information",
    body: [
      "To create and manage accounts, authenticate users, provide subscriptions, and enforce access controls.",
      "To operate InsidrsAI features, including insider-event feeds, AI signal summaries, ticker pages, alerts, trade-plan displays, and administrative tools.",
      "To process payments, manage trials, confirm subscription status, and prevent billing abuse.",
      "To provide customer support, respond to feedback, debug issues, improve product quality, and monitor platform reliability.",
      "To protect the service from fraud, unauthorized access, scraping, spam, abuse, or other harmful activity.",
    ],
  },
  {
    title: "Financial data and AI outputs",
    body: [
      "InsidrsAI processes public securities filings, market data, issuer information, and derived analytics. This information may be stored, cached, transformed, ranked, or summarized.",
      "AI-generated summaries, ratings, trade plans, and explanations are informational product outputs. They are not personal financial advice and should not be treated as a recommendation to buy, sell, or hold any security.",
    ],
  },
  {
    title: "How we share information",
    body: [
      "We share information with service providers that help operate the product, including hosting, analytics, authentication, payment processing, email, support, and infrastructure vendors.",
      "We may share information when required by law, legal process, regulatory request, or to protect the rights, safety, and security of InsidrsAI, our users, or others.",
      "We do not sell personal information. We do not share full payment card details because payment processing is handled by Stripe.",
    ],
  },
  {
    title: "Cookies and authentication",
    body: [
      "We use cookies and similar technologies to keep users signed in, secure sessions, remember preferences, and operate the application.",
      "Some cookies are required for the service to function. Disabling required cookies may prevent login, billing, or app access from working correctly.",
    ],
  },
  {
    title: "Data retention",
    body: [
      "We keep account, subscription, support, and product records for as long as needed to provide the service, comply with legal obligations, resolve disputes, prevent abuse, and maintain business records.",
      "Public market and filing data may remain in our systems as part of historical datasets even if an account is deleted.",
    ],
  },
  {
    title: "Security",
    body: [
      "We use reasonable technical and organizational safeguards, including hashed passwords, access controls, and restricted administrative tools.",
      "No internet service can be guaranteed completely secure. You are responsible for keeping your account credentials confidential and notifying us of suspected unauthorized access.",
    ],
  },
  {
    title: "Your choices",
    body: [
      "You may update profile preferences in the app, opt out of optional alerts where available, and cancel paid subscriptions through the billing flow.",
      "You may request account deletion or data access by contacting us. We may need to retain certain records where required for security, legal, tax, billing, or legitimate business purposes.",
    ],
  },
  {
    title: "Children",
    body: [
      "InsidrsAI is not intended for children under 13, and we do not knowingly collect personal information from children under 13.",
    ],
  },
  {
    title: "Changes to this policy",
    body: [
      "We may update this Privacy Policy from time to time. When we make material changes, we will update the effective date and may provide additional notice in the product or by other reasonable means.",
    ],
  },
  {
    title: "Contact",
    body: [
      "Questions about this Privacy Policy can be sent to support@insidrsai.com.",
    ],
  },
];

export function PrivacyPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-8 py-12">
      <div>
        <div className="badge">Last updated May 19, 2026</div>
        <h1 className="mt-4 text-3xl font-semibold">Privacy Policy</h1>
        <p className="mt-3 text-sm leading-7 muted">
          This Privacy Policy explains how InsidrsAI collects, uses, shares, and protects information when you use our
          website, application, subscription services, and related features.
        </p>
      </div>

      <div className="space-y-5">
        {sections.map((section) => (
          <section key={section.title} className="glass-card p-5">
            <h2 className="text-lg font-semibold">{section.title}</h2>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 muted">
              {section.body.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
