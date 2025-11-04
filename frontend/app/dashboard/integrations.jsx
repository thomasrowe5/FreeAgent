"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { getJSON } from "@/lib/api";

export default function Integrations() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const data = await getJSON("/integrations/status");
        if (mounted) {
          setIntegrations(data.integrations || []);
          setError(null);
        }
      } catch (err) {
        console.error(err);
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load integrations");
        }
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const toggleIntegration = (key) => {
    setIntegrations((prev) =>
      prev.map((integration) =>
        integration.key === key
          ? { ...integration, enabled: !integration.enabled }
          : integration
      )
    );
  };

  return (
    <main style={{ padding: 24, maxWidth: 720, margin: "0 auto", display: "grid", gap: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h2 style={{ marginBottom: 4 }}>Integrations</h2>
          <p style={{ margin: 0, color: "#6b7280" }}>
            Connect your workspace tools to sync activity and automate workflows.
          </p>
        </div>
        <Link href="/dashboard">← Back to dashboard</Link>
      </header>

      {error && (
        <div style={{ padding: 12, background: "#fee2e2", borderRadius: 8, color: "#b91c1c" }}>
          {error}
        </div>
      )}

      {loading ? (
        <p>Loading integrations…</p>
      ) : (
        <section style={{ display: "grid", gap: 16 }}>
          {integrations.map((integration) => {
            const configured = integration.configured;
            const enabled = integration.enabled ?? configured;
            return (
              <div
                key={integration.key}
                style={{
                  border: "1px solid #e5e7eb",
                  borderRadius: 12,
                  padding: 20,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div>
                  <h3 style={{ margin: "0 0 4px" }}>{integration.name}</h3>
                  <p style={{ margin: 0, color: "#6b7280" }}>
                    {configured
                      ? "Connected via OAuth2"
                      : "Not connected. Add credentials in environment variables or complete OAuth2 setup."}
                  </p>
                </div>
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={() => toggleIntegration(integration.key)}
                    disabled={!configured}
                    style={{ width: 20, height: 20 }}
                  />
                  <span style={{ color: configured ? "#111827" : "#9ca3af" }}>
                    {configured ? (enabled ? "Enabled" : "Disabled") : "Configure to enable"}
                  </span>
                </label>
              </div>
            );
          })}
          {integrations.length === 0 && <p>No integrations available yet.</p>}
        </section>
      )}
    </main>
  );
}
