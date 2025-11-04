"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ResponsiveContainer, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip } from "recharts";

import { getJSON, postJSON } from "@/lib/api";

export default function OrganizationPage() {
  const [members, setMembers] = useState([]);
  const [usage, setUsage] = useState({ month: "", total: 0, breakdown: {} });
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState("");
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      setLoading(true);
      const [membersResp, statusResp] = await Promise.all([
        getJSON("/org/members"),
        getJSON("/billing/status"),
      ]);
      setMembers(membersResp.members || []);
      setUsage(membersResp.usage || { month: "", total: 0, breakdown: {} });
      setStatus(statusResp);
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to load organization data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleInvite = async () => {
    try {
      await postJSON("/org/invite", { email: inviteEmail });
      setInviteEmail("");
      await load();
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to create invite");
    }
  };

  const usageData = useMemo(() => {
    return Object.entries(usage.breakdown || {}).map(([action, count]) => ({ action, count }));
  }, [usage]);

  return (
    <main style={{ padding: 24, maxWidth: 960 }}>
      <h2>Organization</h2>
      {loading && <p>Loading organization data...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}

      <section style={{ marginTop: 24, border: "1px solid #e5e7eb", borderRadius: 12, padding: 16 }}>
        <h3>Plan</h3>
        <p>Current plan: {status?.plan ?? "free"}</p>
        <p>
          Usage ({usage.month || "current"}): {usage.total} / {status?.limit ?? "∞"}
        </p>
        <Link href="/dashboard/billing">Manage billing →</Link>
      </section>

      <section style={{ marginTop: 24, border: "1px solid #e5e7eb", borderRadius: 12, padding: 16 }}>
        <h3>Team Members</h3>
        <ul>
          {members.map((member) => (
            <li key={member.id}>{member.email || member.id}</li>
          ))}
        </ul>
        <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
          <input
            type="email"
            placeholder="teammate@example.com"
            value={inviteEmail}
            onChange={(event) => setInviteEmail(event.target.value)}
          />
          <button onClick={handleInvite}>Send Invite</button>
        </div>
      </section>

      <section style={{ marginTop: 24, border: "1px solid #e5e7eb", borderRadius: 12, padding: 16 }}>
        <h3>Usage Breakdown</h3>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={usageData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="action" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="count" fill="#2563eb" />
          </BarChart>
        </ResponsiveContainer>
      </section>
    </main>
  );
}
