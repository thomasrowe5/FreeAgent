"use client";

import { useEffect, useState } from "react";

import { getJSON, postJSON } from "@/lib/api";

export default function BillingPage() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [upgradeLoading, setUpgradeLoading] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await getJSON("/billing/status");
        setStatus(data);
        setError(null);
      } catch (err) {
        console.error(err);
        setError(err instanceof Error ? err.message : "Failed to load billing status");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleUpgrade() {
    try {
      setUpgradeLoading(true);
      const { checkout_url } = await postJSON("/billing/upgrade", {});
      if (checkout_url) {
        window.location.href = checkout_url;
      }
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to start upgrade");
    } finally {
      setUpgradeLoading(false);
    }
  }

  return (
    <main style={{ padding: 24 }}>
      <h2>Billing</h2>
      {loading && <p>Loading billing status...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}
      {status && (
        <section style={{ display: "grid", gap: 12, maxWidth: 420 }}>
          <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16 }}>
            <strong>Plan</strong>
            <p style={{ margin: "4px 0" }}>{status.plan ?? "free"}</p>
            <p style={{ margin: "4px 0" }}>
              Usage this month ({status.month}): {status.usage} / {status.limit}
            </p>
            <p style={{ margin: "4px 0" }}>Remaining: {status.remaining}</p>
            <button onClick={handleUpgrade} disabled={upgradeLoading} style={{ marginTop: 12 }}>
              {upgradeLoading ? "Redirecting..." : "Upgrade"}
            </button>
          </div>

          {status.breakdown && (
            <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 16 }}>
              <strong>Usage Breakdown</strong>
              <ul style={{ marginTop: 8 }}>
                {Object.entries(status.breakdown).map(([action, count]) => (
                  <li key={action}>
                    {action}: {count}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
