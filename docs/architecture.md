# 🧠 FreeAgent – System Architecture

**FreeAgent** is an AI-powered operations manager for freelancers.  
It automates lead capture, proposal drafting, follow-ups, scheduling, and invoicing through a unified agent stack.

---

## 🧩 Core Components
| Layer | Description |
|-------|--------------|
| **Frontend (Next.js)** | Dashboard for managing leads, proposals, and analytics. |
| **Backend (FastAPI)** | API + orchestration layer handling data flow and AI agent tasks. |
| **LLM Agent Layer** | Proposal drafting, lead scoring, and follow-up generation. |
| **Database (PostgreSQL)** | Stores users, leads, deals, proposals, invoices, events. |
| **Cache / Queue (Redis)** | Background jobs: email parsing, follow-ups, analytics updates. |
| **Integrations** | Gmail, Google Calendar, Stripe, Notion (optional). |

---

## ⚙️ Data Flow
```text
Inbound Email ➜ Lead Scorer ➜ CRM ➜ Proposal Generator
   ↘ Human Review ➜ Send via Gmail ➜ Follow-Up Scheduler ➜ Calendar/Invoice
🚀 Deployment Plan
Layer	Platform	Notes
Frontend	Vercel	Auto-build from main
API / Worker	Render or Fly.io	FastAPI + Celery/Redis
DB	Neon / Supabase	Managed Postgres
Storage	Cloudflare R2	Proposal PDFs
Monitoring	Grafana Cloud / UptimeRobot	Health & latency alerts
🔐 Security & Compliance
OAuth scopes: Gmail send/readonly, Calendar events, Stripe payments
PII redaction in logs
Encrypted .env secrets
Daily encrypted DB snapshots
📈 Next Milestones
 Lead intelligence MVP
 Proposal generator + approval UI
 Automated follow-up pipeline
 Stripe invoicing + analytics
 Team (Pod) workspace support
