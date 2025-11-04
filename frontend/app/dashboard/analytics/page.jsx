"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ResponsiveContainer, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip } from "recharts";

import { getJSON } from "@/lib/api";

export default function AnalyticsDashboard() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ start: "", end: "", clientType: "all" });

  const fetchSummary = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (filters.start) params.set("start", filters.start);
      if (filters.end) params.set("end", filters.end);
      if (filters.clientType && filters.clientType !== "all") {
        params.set("client_type", filters.clientType);
      }
      const qs = params.toString();
      const data = await getJSON(`/analytics/summary${qs ? `?${qs}` : ""}`);
      setSummary(data);
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 60_000);
    return () => clearInterval(interval);
  }, [fetchSummary]);

  const kpis = useMemo(() => {
    if (!summary) {
      return {
        conversion: "-",
        revenue: "-",
        leads: "-",
      };
    }
    return {
      conversion: `${Math.round((summary.conversion_rate || 0) * 100)}%`,
      revenue: `$${(summary.revenue || 0).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`,
      leads: summary.leads ?? 0,
    };
  }, [summary]);

  const statusData = useMemo(() => {
    if (!summary?.status_breakdown) return [];
    return Object.entries(summary.status_breakdown).map(([status, count]) => ({ status, count }));
  }, [summary]);

  const revenueData = useMemo(() => {
    if (!summary?.revenue_by_month) return [];
    return summary.revenue_by_month.map((row) => ({
      month: row.month,
      revenue: row.revenue,
    }));
  }, [summary]);

  return (
    <main style={{ padding: 24 }}>
      <h2>Analytics</h2>
      {loading && <p>Loading analytics...</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}

      <section style={{ display: "flex", gap: 12, margin: "12px 0" }}>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <label>Start Date</label>
          <input
            type="date"
            value={filters.start}
            onChange={(event) => setFilters((prev) => ({ ...prev, start: event.target.value }))}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <label>End Date</label>
          <input
            type="date"
            value={filters.end}
            onChange={(event) => setFilters((prev) => ({ ...prev, end: event.target.value }))}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <label>Client Type</label>
          <select
            value={filters.clientType}
            onChange={(event) => setFilters((prev) => ({ ...prev, clientType: event.target.value }))}
          >
            <option value="all">All</option>
            <option value="general">General</option>
            <option value="enterprise">Enterprise</option>
            <option value="startup">Startup</option>
            <option value="nonprofit">Nonprofit</option>
          </select>
        </div>
        <button onClick={fetchSummary} style={{ alignSelf: "flex-end", height: 36 }}>
          Refresh
        </button>
      </section>

      <section style={{ display: "flex", gap: 16, margin: "16px 0" }}>
        <KpiCard label="Total Leads" value={kpis.leads} />
        <KpiCard label="Conversion Rate" value={kpis.conversion} />
        <KpiCard label="Revenue" value={kpis.revenue} />
      </section>

      <section style={{ display: "grid", gap: 24, gridTemplateColumns: "1fr 1fr" }}>
        <div style={{ minHeight: 320, border: "1px solid #eee", borderRadius: 8, padding: 16 }}>
          <h3>Revenue by Month</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={revenueData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="revenue" fill="#2563eb" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ minHeight: 320, border: "1px solid #eee", borderRadius: 8, padding: 16 }}>
          <h3>Status Breakdown</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={statusData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="status" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="#f97316" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </main>
  );
}

function KpiCard({ label, value }) {
  return (
    <div
      style={{
        flex: 1,
        border: "1px solid #eee",
        borderRadius: 8,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <span style={{ fontSize: 12, textTransform: "uppercase", color: "#6b7280" }}>{label}</span>
      <strong style={{ fontSize: 24 }}>{value}</strong>
    </div>
  );
}
