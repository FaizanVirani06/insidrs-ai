import { Link } from "react-router-dom";

export function LegalPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-8 py-12">
      <div>
        <div className="badge">Last updated May 19, 2026</div>
        <h1 className="mt-4 text-3xl font-semibold">Legal</h1>
        <p className="mt-3 text-sm leading-7 muted">
          InsidrsAI provides informational research tools for public insider activity, market data, AI-generated
          summaries, and technical trade-plan examples. The documents below explain how the service works, how
          information is handled, and the rules that apply when using the product.
        </p>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <section className="glass-card p-6">
          <h2 className="text-xl font-semibold">Privacy Policy</h2>
          <p className="mt-3 text-sm leading-7 muted">
            Learn what account, billing, usage, support, and product information we collect, how we use it, and the
            choices available to you.
          </p>
          <Link to="/privacy" className="btn-secondary mt-5">
            Read Privacy Policy
          </Link>
        </section>

        <section className="glass-card p-6">
          <h2 className="text-xl font-semibold">Terms of Service</h2>
          <p className="mt-3 text-sm leading-7 muted">
            Review the terms for using InsidrsAI, including subscription rules, acceptable use, AI and data limitations,
            and investment-risk disclaimers.
          </p>
          <Link to="/terms" className="btn-secondary mt-5">
            Read Terms of Service
          </Link>
        </section>
      </div>

      <section className="glass-card p-5">
        <h2 className="text-lg font-semibold">Important investment disclosure</h2>
        <p className="mt-3 text-sm leading-7 muted">
          InsidrsAI is for informational and educational purposes only. We are not a broker-dealer, investment adviser,
          financial planner, legal adviser, tax adviser, or fiduciary. Nothing in the product is investment advice or a
          recommendation to buy, sell, or hold any security. Trading and investing involve risk, including possible loss
          of principal.
        </p>
      </section>
    </div>
  );
}
