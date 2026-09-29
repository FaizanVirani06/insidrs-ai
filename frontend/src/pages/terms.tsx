const sections = [
  {
    title: "Acceptance of terms",
    body: [
      "By accessing or using InsidrsAI, you agree to these Terms of Service. If you do not agree, do not use the service.",
      "You must be legally able to enter into these terms and comply with all laws that apply to your use of the service.",
    ],
  },
  {
    title: "Informational use only",
    body: [
      "InsidrsAI provides market data, insider filing analysis, AI-generated summaries, rankings, trade-plan examples, and related research tools for informational and educational purposes only.",
      "InsidrsAI is not a broker-dealer, investment adviser, financial planner, legal adviser, tax adviser, or fiduciary.",
      "Nothing in the service is investment advice, a recommendation, an offer to buy or sell securities, or a guarantee of investment performance.",
      "You are solely responsible for your investment decisions. Consult qualified professionals before making financial, legal, tax, or investment decisions.",
    ],
  },
  {
    title: "Market data and AI limitations",
    body: [
      "Data may be delayed, incomplete, inaccurate, unavailable, or affected by third-party provider issues, filing errors, market events, or system failures.",
      "AI outputs can be wrong, incomplete, outdated, or misleading. You should independently verify all information before relying on it.",
      "Trade plans are beta, technical, and heuristic examples based on available data. They are not tailored to your objectives, risk tolerance, account size, or financial situation.",
    ],
  },
  {
    title: "Accounts and security",
    body: [
      "You are responsible for maintaining the confidentiality of your login credentials and for all activity under your account.",
      "You agree to provide accurate account information and promptly update it when necessary.",
      "We may suspend or terminate accounts that appear to be compromised, abusive, fraudulent, unlawful, or in violation of these terms.",
    ],
  },
  {
    title: "Subscriptions, trials, and billing",
    body: [
      "Paid features may require an active subscription. Subscription billing is processed by Stripe or another payment provider.",
      "Trials, discounts, prices, billing periods, and included features may change over time unless prohibited by law or an active agreement.",
      "You are responsible for cancelling before renewal if you do not want to continue a paid subscription.",
      "Refunds are not guaranteed except where required by law or expressly stated by InsidrsAI.",
    ],
  },
  {
    title: "Acceptable use",
    body: [
      "Do not misuse the service, attempt unauthorized access, interfere with platform operation, bypass paywalls, scrape at unreasonable volume, reverse engineer non-public systems, or use the service to violate laws or third-party rights.",
      "Do not resell, redistribute, or commercially exploit InsidrsAI outputs or data except as expressly allowed in writing.",
      "Do not use the service to make false, misleading, manipulative, or unlawful market statements.",
    ],
  },
  {
    title: "Intellectual property",
    body: [
      "InsidrsAI and its software, design, branding, compilations, analytics, summaries, and other materials are owned by InsidrsAI or its licensors.",
      "Subject to these terms, we grant you a limited, revocable, non-exclusive, non-transferable right to use the service for your own internal informational purposes.",
      "You retain rights to content you submit, but you grant InsidrsAI permission to use it as needed to operate, secure, support, and improve the service.",
    ],
  },
  {
    title: "Third-party services",
    body: [
      "The service may rely on third-party providers for market data, filings, AI models, payments, hosting, support, and other functions.",
      "Third-party services may have their own terms, privacy policies, outages, limitations, or fees. InsidrsAI is not responsible for third-party acts or omissions.",
    ],
  },
  {
    title: "No warranties",
    body: [
      "The service is provided on an as-is and as-available basis. To the maximum extent permitted by law, InsidrsAI disclaims all warranties, express or implied, including warranties of accuracy, reliability, availability, merchantability, fitness for a particular purpose, and non-infringement.",
      "We do not warrant that the service will be uninterrupted, error-free, secure, complete, or that any data or output will meet your expectations.",
    ],
  },
  {
    title: "Limitation of liability",
    body: [
      "To the maximum extent permitted by law, InsidrsAI will not be liable for indirect, incidental, special, consequential, exemplary, punitive, or lost-profit damages, or for trading losses, investment losses, data losses, or business interruptions.",
      "To the maximum extent permitted by law, our total liability for any claim relating to the service will not exceed the amount you paid to InsidrsAI for the service in the three months before the event giving rise to the claim.",
    ],
  },
  {
    title: "Indemnification",
    body: [
      "You agree to indemnify and hold harmless InsidrsAI from claims, losses, liabilities, damages, costs, and expenses arising from your misuse of the service, violation of these terms, violation of law, or infringement of another party's rights.",
    ],
  },
  {
    title: "Termination",
    body: [
      "You may stop using the service at any time. We may suspend, restrict, or terminate access if we believe you violated these terms, created risk, failed to pay, or used the service unlawfully or abusively.",
      "Sections that by their nature should survive termination will survive, including intellectual property, disclaimers, limitations of liability, indemnification, and payment obligations.",
    ],
  },
  {
    title: "Changes",
    body: [
      "We may update these Terms of Service from time to time. Continued use of the service after changes become effective means you accept the updated terms.",
    ],
  },
  {
    title: "Contact",
    body: [
      "Questions about these Terms of Service can be sent to support@insidrsai.com.",
    ],
  },
];

export function TermsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-8 py-12">
      <div>
        <div className="badge">Last updated May 19, 2026</div>
        <h1 className="mt-4 text-3xl font-semibold">Terms of Service</h1>
        <p className="mt-3 text-sm leading-7 muted">
          These Terms of Service govern your access to and use of InsidrsAI, including our website, application,
          subscription services, analytics, AI-generated outputs, and related tools.
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
