export default function Pricing() {
  return (
    <main style={{ padding: 24 }}>
      <h2>Pricing</h2>
      <ul>
        <li>
          <b>Free</b>: 20 actions per month
        </li>
        <li>
          <b>Pro</b>: $19 per month - unlimited actions, follow-ups, analytics
        </li>
      </ul>
      <button onClick={() => alert("Hook to Stripe Checkout next")}>Go Pro</button>
    </main>
  );
}
