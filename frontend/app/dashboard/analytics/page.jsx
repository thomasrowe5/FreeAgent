"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ResponsiveContainer, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, LineChart, Line, Legend } from "recharts";

import { getJSON } from "@/lib/api";

export default function AnalyticsDashboard() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ start: "", end: "", clientType: "all" });
  const [revenueOverview, setRevenueOverview] = useState(null);
  const [streamPoints, setStreamPoints] = useState([]);

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

  const fetchRevenueOverview = useCallback(async () => {
    try {
      const data = await getJSON("/analytics/revenue");
      setRevenueOverview(data);
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => {
    fetchSummary();
    const interval = setInterval(fetchSummary, 60_000);
    return () => clearInterval(interval);
  }, [fetchSummary]);

  useEffect(() => {
    fetchRevenueOverview();
    const interval = setInterval(fetchRevenueOverview, 60_000);
    return () => clearInterval(interval);
  }, [fetchRevenueOverview]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const base = (process.env.NEXT_PUBLIC_API_URL || window.location.origin).replace(/\/$/, "");
    const wsUrl = base
      .replace(/^https:/i, "wss:")
      .replace(/^http:/i, "ws:") + "/ws/metrics";
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setStreamPoints((prev) => {
          const next = prev.slice(-99);
          next.push({
            ...data,
            timestamp: data.timestamp || new Date().toISOString(),
          });
          return next;
        });
      } catch (err) {
        console.error("Failed to parse metrics event", err);
      }
    };

    ws.onerror = (event) => {
      console.error("Metrics websocket error", event);
    };

    return () => {
      ws.close();
    };
  }, []);

  const kpis = useMemo(() => {
    if (!summary && !revenueOverview) {
      return {
        conversion: "-",
        revenue: "-",
        leads: "-",
      };
    }
    const conversionRate =
      "conversion_rate" in (revenueOverview || {})
        ? revenueOverview?.conversion_rate ?? 0
        : summary?.conversion_rate ?? 0;
    const totalRevenue =
      "total_revenue" in (revenueOverview || {})
        ? revenueOverview?.total_revenue ?? 0
        : summary?.revenue ?? 0;

    return {
      conversion: `${Math.round((conversionRate || 0) * 100)}%`,
      revenue: `$${(totalRevenue || 0).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`,
      leads: summary?.leads ?? 0,
    };
  }, [summary, revenueOverview]);

  const statusData = useMemo(() => {
    if (!summary?.status_breakdown) return [];
    return Object.entries(summary.status_breakdown).map(([status, count]) => ({ status, count }));
  }, [summary]);

  const revenueData = useMemo(() => {
    const rows =
      revenueOverview?.monthly ?? summary?.revenue_by_month ?? [];
    return rows.map((row) => ({
      month: row.month,
      revenue: row.revenue,
    }));
  }, [revenueOverview, summary]);

  const metricsChartData = useMemo(
    () =>
      streamPoints.map((point, index) => ({
        index,
        timestamp: point.timestamp,
        latency: point.duration_ms ?? 0,
        tokens: point.token_usage ?? 0,
        cost: point.cost ?? 0,
      })),
    [streamPoints]
  );

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

      <section
        style={{
          marginTop: 24,
          border: "1px solid #eee",
          borderRadius: 8,
          padding: 16,
          minHeight: 320,
        }}
      >
        <h3>Agent Run Metrics</h3>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={metricsChartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="timestamp" />
            <YAxis yAxisId="left" label={{ value: "Latency (ms)", angle: -90, position: "insideLeft" }} />
            <YAxis
              yAxisId="right"
              orientation="right"
              label={{ value: "Tokens / Cost", angle: 90, position: "insideRight" }}
            />
            <Tooltip />
            <Legend />
            <Line yAxisId="left" type="monotone" dataKey="latency" stroke="#2563eb" name="Latency" dot={false} />
            <Line yAxisId="right" type="monotone" dataKey="tokens" stroke="#16a34a" name="Tokens" dot={false} />
            <Line yAxisId="right" type="monotone" dataKey="cost" stroke="#f97316" name="Cost" dot={false} />
          </LineChart>
        </ResponsiveContainer>
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
