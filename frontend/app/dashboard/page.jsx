"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getJSON, postJSON } from "@/lib/api";

export default function Dashboard() {
  const [leads, setLeads] = useState([]);
  const [form, setForm] = useState({
    name: "Acme",
    email: "ceo@acme.com",
    message: "Budget $5-10k, timeline 3 weeks.",
    value: "10000",
    clientType: "general",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [proposalDrafts, setProposalDrafts] = useState({});
  const [editedProposals, setEditedProposals] = useState({});
  const [feedbackComments, setFeedbackComments] = useState({});
  const [feedbackTypes, setFeedbackTypes] = useState({});

  async function refresh() {
    try {
      const data = await getJSON("/leads");
      setLeads(data);
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to load leads");
      setLeads([]);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addLead() {
    setLoading(true);
    try {
      await postJSON("/leads", {
        ...form,
        value: form.value ? parseFloat(form.value) : null,
        client_type: form.clientType,
      });
      setForm({ name: "", email: "", message: "", value: "", clientType: "general" });
      await refresh();
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to add lead");
    } finally {
      setLoading(false);
    }
  }

  async function genProposal(leadId) {
    setLoading(true);
    try {
      const proposal = await postJSON("/proposals", { lead_id: leadId });
      setProposalDrafts((prev) => ({ ...prev, [leadId]: proposal.content }));
      setEditedProposals((prev) => ({ ...prev, [leadId]: proposal.content }));
      await refresh();
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to generate proposal");
    } finally {
      setLoading(false);
    }
  }

  async function scheduleFollowup(leadId) {
    setLoading(true);
    try {
      await postJSON("/followups", { lead_id: leadId, days_after: 3 });
      await refresh();
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to schedule follow-up");
    } finally {
      setLoading(false);
    }
  }

  async function submitFeedback(leadId) {
    try {
      setLoading(true);
      await postJSON("/feedback", {
        lead_id: leadId,
        type: feedbackTypes[leadId] || "proposal_edit",
        comment: feedbackComments[leadId] || "",
        edited_text: editedProposals[leadId] || "",
      });
      setError(null);
      alert("Feedback submitted. Thank you!");
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Failed to submit feedback");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 900 }}>
      <h2>Leads</h2>
      <div style={{ margin: "8px 0" }}>
        <Link href="/dashboard/analytics">View analytics →</Link>
        <span style={{ margin: "0 8px" }}>|</span>
        <Link href="/dashboard/billing">Billing →</Link>
      </div>
      {error && <p style={{ color: "red" }}>{error}</p>}
      <div style={{ display: "grid", gap: 12, margin: "12px 0" }}>
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
        <button onClick={addLead} disabled={loading}>
          {loading ? "..." : "Add Lead"}
        </button>
      </div>

      {leads.length === 0 && <p>No leads yet.</p>}
      {leads.map((lead) => {
        const statusText = `score ${lead.score} - ${lead.status} - ${lead.client_type} - value $${Number(
          lead.value || 0,
        ).toLocaleString()}`;
        return (
          <div
            key={lead.id}
            style={{ border: "1px solid #eee", padding: 12, borderRadius: 8, marginBottom: 10 }}
          >
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <strong>
                {lead.name} - {lead.email}
              </strong>
              <span>{statusText}</span>
            </div>
            <p>{lead.message}</p>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={() => genProposal(lead.id)}>Generate Proposal</button>
              <button onClick={() => scheduleFollowup(lead.id)}>Schedule Follow-up</button>
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
                <button onClick={() => submitFeedback(lead.id)} disabled={loading}>
                  {loading ? "Submitting..." : "Submit Feedback"}
                </button>
              </div>
            )}
          </div>
        );
      })}
    </main>
  );
}
