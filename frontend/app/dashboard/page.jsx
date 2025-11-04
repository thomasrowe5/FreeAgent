"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ComposedChart,
} from "recharts";

import { getJSON, postJSON } from "@/lib/api";

const TABS = ["Agents", "Jobs", "Analytics", "Logs", "Settings"];

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("Jobs");
  const [error, setError] = useState(null);

  const resolvedApiBase = useMemo(() => {
    const baseEnv = process.env.NEXT_PUBLIC_API_URL || "";
    if (baseEnv) return baseEnv.replace(/\/$/, "");
    if (typeof window !== "undefined") {
      return window.location.origin.replace(/\/$/, "");
    }
    return "";
  }, []);

  const wsBase = useMemo(() => {
    if (!resolvedApiBase) return "";
    if (resolvedApiBase.startsWith("https")) return resolvedApiBase.replace("https", "wss");
    if (resolvedApiBase.startsWith("http")) return resolvedApiBase.replace("http", "ws");
    return resolvedApiBase;
  }, [resolvedApiBase]);

  // Agents tab state
  const [agents, setAgents] = useState([]);
  const [agentsLoading, setAgentsLoading] = useState(false);

  // Jobs (lead) state
  const [leads, setLeads] = useState([]);
  const [jobRuns, setJobRuns] = useState([]);
  const [orgId, setOrgId] = useState("");
  const wsRef = useRef(null);
  const [form, setForm] = useState({
    name: "Acme",
    email: "ceo@acme.com",
    message: "Budget $5-10k, timeline 3 weeks.",
    value: "10000",
    clientType: "general",
  });
  const [loading, setLoading] = useState(false);
  const [proposalDrafts, setProposalDrafts] = useState({});
  const [editedProposals, setEditedProposals] = useState({});
  const [feedbackComments, setFeedbackComments] = useState({});
  const [feedbackTypes, setFeedbackTypes] = useState({});

  // Logs tab state
  const [logs, setLogs] = useState([]);

  // Settings tab state
  const [selectedAgent, setSelectedAgent] = useState("");
  const [promptDraft, setPromptDraft] = useState("");
  const [savingPrompt, setSavingPrompt] = useState(false);

  const fetchLeads = useCallback(async () => {
    try {
      const data = await getJSON("/leads");
      setLeads(data);
      setOrgId(data[0]?.org_id || "");
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to load leads");
      setLeads([]);
    }
  }, []);

  const fetchAgents = useCallback(async () => {
    try {
      setAgentsLoading(true);
      const data = await getJSON("/agents/status");
      setAgents(data);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to load agents");
    } finally {
      setAgentsLoading(false);
    }
  }, []);

  const fetchJobRuns = useCallback(async () => {
    try {
      const data = await getJSON("/orchestrate/runs");
      setJobRuns(data.runs || []);
    } catch (err) {
      console.error(err);
    }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const data = await getJSON("/logs/recent");
      setLogs(data);
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "Agents") {
      fetchAgents();
      const interval = setInterval(fetchAgents, 60_000);
      return () => clearInterval(interval);
    }
  }, [activeTab, fetchAgents]);

  useEffect(() => {
    if (activeTab === "Settings" && agents.length === 0) {
      fetchAgents();
    }
  }, [activeTab, agents.length, fetchAgents]);
  useEffect(() => {
    if (activeTab === "Jobs") {
      fetchLeads();
      fetchJobRuns();
      const baseForWs = wsBase || (typeof window !== "undefined" ? window.location.origin.replace(/\/$/, "") : "");
      const wsUrl = baseForWs ? `${baseForWs}/orchestrate/ws` : "/orchestrate/ws";
      try {
        const socket = new WebSocket(wsUrl);
        wsRef.current = socket;
        socket.onmessage = (event) => {
          try {
            const payload = JSON.parse(event.data);
            if (payload.runs) {
              setJobRuns(
                payload.runs.filter(
                  (run) => !orgId || !run.context || !run.context.org_id || run.context.org_id === orgId,
                ),
              );
            } else {
              if (!orgId || !payload.context || !payload.context.org_id || payload.context.org_id === orgId) {
                setJobRuns((prev) => [payload, ...prev].slice(0, 50));
              }
            }
          } catch (err) {
            console.error("Failed to parse websocket payload", err);
          }
        };
        socket.onerror = (err) => console.error("WebSocket error", err);
      } catch (err) {
        console.error("WebSocket init failed", err);
      }
      return () => {
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }
      };
    }
  }, [activeTab, fetchLeads, fetchJobRuns, wsBase, orgId]);

  useEffect(() => {
    if (activeTab === "Logs") {
      fetchLogs();
      const interval = setInterval(fetchLogs, 15_000);
      return () => clearInterval(interval);
    }
  }, [activeTab, fetchLogs]);

  const handleAddLead = async () => {
    setLoading(true);
    try {
      await postJSON("/leads", {
        ...form,
        value: form.value ? parseFloat(form.value) : null,
        client_type: form.clientType,
      });
      setForm({ name: "", email: "", message: "", value: "", clientType: "general" });
      await fetchLeads();
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to add lead");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateProposal = async (leadId) => {
    setLoading(true);
    try {
      const proposal = await postJSON("/proposals", { lead_id: leadId });
      setProposalDrafts((prev) => ({ ...prev, [leadId]: proposal.content }));
      setEditedProposals((prev) => ({ ...prev, [leadId]: proposal.content }));
      await fetchLeads();
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to generate proposal");
    } finally {
      setLoading(false);
    }
  };

  const handleFollowup = async (leadId) => {
    setLoading(true);
    try {
      await postJSON("/followups", { lead_id: leadId, days_after: 3 });
      await fetchLeads();
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to schedule follow-up");
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (leadId) => {
    try {
      setLoading(true);
      await postJSON("/feedback", {
        lead_id: leadId,
        type: feedbackTypes[leadId] || "proposal_edit",
        comment: feedbackComments[leadId] || "",
        edited_text: editedProposals[leadId] || "",
      });
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to submit feedback");
    } finally {
      setLoading(false);
    }
  };

  const loadAgentPrompt = useCallback(
    async (name) => {
      if (!name) return;
      try {
        const data = await getJSON(`/agents/config/${name}`);
        setPromptDraft(data.prompt_template || "");
      } catch (err) {
        console.error(err);
        setPromptDraft("");
      }
    },
    []
  );

  useEffect(() => {
    if (activeTab === "Settings" && !selectedAgent && agents.length > 0) {
      setSelectedAgent(agents[0].name);
      loadAgentPrompt(agents[0].name);
    }
  }, [activeTab, agents, loadAgentPrompt, selectedAgent]);

  useEffect(() => {
    if (selectedAgent) {
      loadAgentPrompt(selectedAgent);
    }
  }, [selectedAgent, loadAgentPrompt]);

  const handleSavePrompt = async () => {
    if (!selectedAgent) return;
    try {
      setSavingPrompt(true);
      await postJSON("/agents/config/update", {
        name: selectedAgent,
        prompt_template: promptDraft,
      });
      setError(null);
      await fetchAgents();
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to save prompt");
    } finally {
      setSavingPrompt(false);
    }
  };

  const tokenLatencyData = useMemo(() => {
    return agents.map((agent, index) => ({
      name: agent.name,
      tokens: agent.avg_tokens || 0,
      latency: agent.avg_latency_ms || 0,
      index,
    }));
  }, [agents]);

  const renderAgentsTab = () => (
    <section style={{ display: "grid", gap: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3>Agents</h3>
        <button onClick={fetchAgents} disabled={agentsLoading}>
          {agentsLoading ? "Refreshing..." : "Refresh"}
        </button>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={tokenLatencyData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis yAxisId="left" label={{ value: "Tokens", angle: -90, position: "insideLeft" }} />
          <YAxis
            yAxisId="right"
            orientation="right"
            label={{ value: "Latency (ms)", angle: 90, position: "insideRight" }}
          />
          <Tooltip />
          <Legend />
          <Bar yAxisId="left" dataKey="tokens" fill="#2563eb" name="Avg tokens" />
          <Line yAxisId="right" dataKey="latency" stroke="#f97316" name="Latency" />
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ display: "grid", gap: 16 }}>
        {agents.map((agent) => (
          <div key={agent.name} style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>{agent.name}</strong>
              <span>{Math.round((agent.success_rate || 0) * 100)}% success</span>
            </div>
            <p style={{ margin: "8px 0" }}>{agent.goal}</p>
            <div style={{ height: 6, background: "#f3f4f6", borderRadius: 999 }}>
              <div
                style={{
                  width: `${Math.round((agent.success_rate || 0) * 100)}%`,
                  height: "100%",
                  background: "#10b981",
                  borderRadius: 999,
                }}
              />
            </div>
            <p style={{ marginTop: 8 }}>
              Avg tokens: {agent.avg_tokens} · Avg latency: {agent.avg_latency_ms} ms
            </p>
          </div>
        ))}
      </div>
    </section>
  );

  const renderJobsTab = () => (
    <section style={{ display: "grid", gap: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <h3>Lead Intake</h3>
        <div>
          <Link href="/dashboard/analytics">View analytics →</Link>
          <span style={{ margin: "0 8px" }}>|</span>
          <Link href="/dashboard/billing">Billing →</Link>
          <span style={{ margin: "0 8px" }}>|</span>
          <Link href="/dashboard/integrations">Integrations →</Link>
        </div>
      </div>
      {error && <p style={{ color: "red" }}>{error}</p>}
      <div style={{ display: "grid", gap: 12 }}>
        <input
          placeholder="name"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
        <input
          placeholder="email"
          value={form.email}
          onChange={(event) => setForm({ ...form, email: event.target.value })}
        />
        <select
          aria-label="Client type"
          value={form.clientType}
          onChange={(event) => setForm({ ...form, clientType: event.target.value })}
        >
          <option value="general">General</option>
          <option value="enterprise">Enterprise</option>
          <option value="startup">Startup</option>
          <option value="nonprofit">Nonprofit</option>
        </select>
        <input
          placeholder="value"
          type="number"
          value={form.value}
          onChange={(event) => setForm({ ...form, value: event.target.value })}
        />
        <textarea
          placeholder="message"
          value={form.message}
          onChange={(event) => setForm({ ...form, message: event.target.value })}
        />
        <button onClick={handleAddLead} disabled={loading}>
          {loading ? "..." : "Add Lead"}
        </button>
      </div>

      <div>
        <h3>Recent Orchestrations</h3>
        <div style={{ display: "grid", gap: 12 }}>
          {jobRuns.length === 0 && <p>No DAG runs yet.</p>}
          {jobRuns.map((run, index) => (
            <div key={run.timestamp || index} style={{ border: "1px solid #e5e7eb", padding: 12, borderRadius: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>Status: {run.status}</strong>
                <span>{run.timestamp}</span>
              </div>
              <p>Total cost: {run.total_cost}</p>
              <ul>
                {run.nodes?.map((node) => (
                  <li key={node.id}>
                    {node.name}: {node.status} ({node.duration_ms} ms, cost {node.cost})
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3>Leads</h3>
        {leads.length === 0 && <p>No leads yet.</p>}
        {leads.map((lead) => {
          const statusText = `score ${lead.score} - ${lead.status} - ${lead.client_type} - value $${Number(
            lead.value || 0,
          ).toLocaleString()}`;
          return (
            <div key={lead.id} style={{ border: "1px solid #eee", padding: 12, borderRadius: 8, marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>
                  {lead.name} - {lead.email}
                </strong>
                <span>{statusText}</span>
              </div>
              <p>{lead.message}</p>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => handleGenerateProposal(lead.id)}>Generate Proposal</button>
                <button onClick={() => handleFollowup(lead.id)}>Schedule Follow-up</button>
              </div>
              {proposalDrafts[lead.id] && (
                <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
                  <label style={{ fontWeight: 600 }}>Edit proposal</label>
                  <textarea
                    rows={6}
                    value={editedProposals[lead.id] ?? proposalDrafts[lead.id]}
                    onChange={(event) =>
                      setEditedProposals((prev) => ({ ...prev, [lead.id]: event.target.value }))
                    }
                  />
                  <label style={{ fontWeight: 600 }}>Feedback type</label>
                  <select
                    value={feedbackTypes[lead.id] ?? "proposal_edit"}
                    onChange={(event) =>
                      setFeedbackTypes((prev) => ({ ...prev, [lead.id]: event.target.value }))
                    }
                  >
                    <option value="proposal_edit">Proposal edit</option>
                    <option value="tone">Tone</option>
                    <option value="scope">Scope</option>
                    <option value="pricing">Pricing</option>
                    <option value="other">Other</option>
                  </select>
                  <label style={{ fontWeight: 600 }}>Comment (optional)</label>
                  <textarea
                    rows={3}
                    value={feedbackComments[lead.id] ?? ""}
                    onChange={(event) =>
                      setFeedbackComments((prev) => ({ ...prev, [lead.id]: event.target.value }))
                    }
                  />
                  <button onClick={() => handleFeedback(lead.id)} disabled={loading}>
                    {loading ? "Submitting..." : "Submit Feedback"}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );

  const renderAnalyticsTab = () => (
    <section style={{ display: "grid", gap: 16 }}>
      <p>
        Visit the dedicated <Link href="/dashboard/analytics">Analytics dashboard</Link> for full insights. Use the
        filters there to explore conversion and revenue trends.
      </p>
      <p>
        You can also orchestrate a new DAG run via the advanced <code>/orchestrate</code> endpoint to populate this
        timeline.
      </p>
    </section>
  );

  const renderLogsTab = () => (
    <section style={{ display: "grid", gap: 12 }}>
      <h3>Recent Logs</h3>
      {logs.length === 0 && <p>No logs captured yet.</p>}
      {logs.map((log, index) => (
        <div key={log.timestamp || index} style={{ border: "1px solid #e5e7eb", padding: 12, borderRadius: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <strong>{log.stage}</strong>
            <span>{log.timestamp}</span>
          </div>
          <p>Status: {log.status ? "success" : "error"}</p>
          {log.error && <pre style={{ whiteSpace: "pre-wrap" }}>{log.error}</pre>}
        </div>
      ))}
    </section>
  );

  const renderSettingsTab = () => (
    <section style={{ display: "grid", gap: 16, maxWidth: 720 }}>
      <h3>Prompt Templates</h3>
      <p>
        Manage team members and usage on the <Link href="/dashboard/org">Organization page</Link>.
      </p>
      <div style={{ display: "flex", gap: 12 }}>
        <select value={selectedAgent} onChange={(event) => setSelectedAgent(event.target.value)}>
          <option value="">Select agent</option>
          {agents.map((agent) => (
            <option key={agent.name} value={agent.name}>
              {agent.name}
            </option>
          ))}
        </select>
        <button onClick={handleSavePrompt} disabled={savingPrompt || !selectedAgent}>
          {savingPrompt ? "Saving..." : "Save Prompt"}
        </button>
      </div>
      <textarea
        rows={12}
        value={promptDraft}
        onChange={(event) => setPromptDraft(event.target.value)}
        placeholder="Prompt template"
      />
      <p style={{ color: "#6b7280" }}>
        Editing a prompt updates the agent config file and reloads the persona at runtime.
      </p>
    </section>
  );

  const renderActiveTab = () => {
    switch (activeTab) {
      case "Agents":
        return renderAgentsTab();
      case "Jobs":
        return renderJobsTab();
      case "Analytics":
        return renderAnalyticsTab();
      case "Logs":
        return renderLogsTab();
      case "Settings":
        return renderSettingsTab();
      default:
        return null;
    }
  };

  return (
    <main style={{ padding: 24 }}>
      <h2>Command Center</h2>
      <div style={{ display: "flex", gap: 12, margin: "16px 0" }}>
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: "8px 16px",
              borderRadius: 999,
              border: "1px solid #d1d5db",
              backgroundColor: activeTab === tab ? "#2563eb" : "#fff",
              color: activeTab === tab ? "#fff" : "#1f2937",
              fontWeight: 600,
            }}
          >
            {tab}
          </button>
        ))}
      </div>
      {renderActiveTab()}
    </main>
  );
}
