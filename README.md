# FreeAgent

## Overview
FreeAgent is a modular AI-agent freelance platform enabling autonomous lead generation, proposal writing, and client communication. The system pairs configurable agents with a collaborative dashboard so founding teams can orchestrate lead intake, outreach, and follow-ups in one automated workspace.

## Features
- **Lead Scoring & Triage** – ingest inbound requests, classify urgency, and prioritize follow-up actions.
- **Proposal Generation** – craft branded proposals with memory-aware context and tone controls.
- **Automated Follow-ups** – schedule nudges, send Gmail sequences, and log engagement metrics.
- **Analytics & Self-Optimization** – monitor conversion, revenue trends, run history, and trigger weekly prompt tuning.
- **Branding & Campaigns** – manage logos, colors, PDFs, and marketing templates with tone training.

## Tech Stack
- **Backend**: FastAPI, SQLModel, Celery, Redis, Postgres/Neon
- **Frontend**: Next.js (React), Tailwind/shadcn components, Supabase Auth
- **Agents**: OpenAI GPT-4o family, ChromaDB vector memory, custom reward optimizer
- **Ops & Deploy**: Docker Compose, Render (API/worker), Vercel (web)

## Quick Start
```bash
# 1. Clone and install
git clone https://github.com/your-org/freeagent.git
cd freeagent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..

# 2. Configure environment
cp .env.example .env
export OPENAI_API_KEY=sk-yourkey

# 3. Launch stack (API, worker, frontend, Postgres, Redis)
docker compose -f infra/docker-compose.yml up --build

# 4. Seed demo content (optional)
python scripts/seed_demo_data.py
```
- Frontend: http://localhost:3000 (`/dashboard`, `/marketing`)
- API Docs: http://localhost:8000/docs

## Folder Structure
```
backend/           FastAPI services, agents, workflows, branding, analytics
frontend/          Next.js dashboard, marketing builder, Supabase helpers
docs/              Architecture, API reference, guides
infra/             Docker Compose, deployment manifests
scripts/           Data seeding, demo outlines, utilities
data/              Persisted branding assets, optimized prompts, memory stores
```

## Future Roadmap
- **Phase 2**
  - Billing upgrades with usage-based plans and Stripe checkout.
  - Team roles, shared queues, and organizational workspaces.
  - Marketplace for reusable agent templates and vertical-specific playbooks.

## License
Released under the [MIT License](LICENSE).
