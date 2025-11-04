export default function LandingPage() {
  return (
    <main style={{ fontFamily: "Inter, sans-serif" }}>
      <section
        style={{
          padding: "80px 24px",
          background: "linear-gradient(135deg, #1d4ed8, #60a5fa)",
          color: "#fff",
          textAlign: "center",
        }}
      >
        <h1 style={{ fontSize: 48, marginBottom: 16 }}>FreeAgent</h1>
        <p style={{ fontSize: 20, maxWidth: 720, margin: "0 auto" }}>
          Automate lead qualification, proposals, and follow-ups so you can focus on closing deals.
        </p>
        <div style={{ marginTop: 32 }}>
          <a
            href="/dashboard"
            style={{
              backgroundColor: "#fff",
              color: "#1d4ed8",
              padding: "12px 24px",
              borderRadius: 8,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            Launch Dashboard
          </a>
        </div>
      </section>

      <section style={{ padding: "64px 24px", backgroundColor: "#f9fafb" }}>
        <h2 style={{ textAlign: "center", marginBottom: 32 }}>Why founders love FreeAgent</h2>
        <div style={{ display: "grid", gap: 24, gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
          {[
            {
              title: "Lead Scoring",
              body: "AI prioritizes inbound leads based on intent, budget, and urgency signals.",
            },
            {
              title: "Proposal Drafts",
              body: "Generate polished proposals in seconds and customize them with your voice.",
            },
            {
              title: "Follow-up Cadence",
              body: "Automated nudges keep conversations alive without sounding robotic.",
            },
          ].map((feature) => (
            <div key={feature.title} style={{ backgroundColor: "#fff", padding: 24, borderRadius: 12 }}>
              <h3 style={{ marginBottom: 12 }}>{feature.title}</h3>
              <p style={{ lineHeight: 1.5 }}>{feature.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section style={{ padding: "64px 24px" }}>
        <h2 style={{ textAlign: "center", marginBottom: 32 }}>Pricing</h2>
        <div style={{ display: "flex", gap: 24, justifyContent: "center", flexWrap: "wrap" }}>
          <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 32, width: 280 }}>
            <h3>Free</h3>
            <p style={{ fontSize: 24, fontWeight: 700 }}>$0</p>
            <ul style={{ listStyle: "none", padding: 0 }}>
              <li>20 automated actions / month</li>
              <li>Lead scoring & proposals</li>
            </ul>
          </div>
          <div style={{ border: "2px solid #1d4ed8", borderRadius: 12, padding: 32, width: 280 }}>
            <h3>Pro</h3>
            <p style={{ fontSize: 24, fontWeight: 700 }}>$19 / month</p>
            <ul style={{ listStyle: "none", padding: 0 }}>
              <li>Unlimited actions</li>
              <li>Advanced analytics</li>
              <li>Team invites & API access</li>
            </ul>
          </div>
        </div>
      </section>

      <section style={{ padding: "64px 24px", textAlign: "center", backgroundColor: "#1d4ed8", color: "#fff" }}>
        <h2>Ready to automate your client pipeline?</h2>
        <p style={{ marginTop: 12 }}>Start the beta today and onboard your team in minutes.</p>
        <a
          href="/dashboard"
          style={{
            marginTop: 24,
            display: "inline-block",
            backgroundColor: "#fff",
            color: "#1d4ed8",
            padding: "12px 24px",
            borderRadius: 8,
            fontWeight: 600,
            textDecoration: "none",
          }}
        >
          Join FreeAgent
        </a>
      </section>
    </main>
  );
}
