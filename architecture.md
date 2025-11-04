## FreeAgent Architecture

### Platform Overview
```
Client (Next.js dashboard / marketing builder)
        ↓ HTTPS (Supabase JWT)
FastAPI API (agents, branding, analytics)
        ↓ task dispatch
Celery Worker / Workflow Orchestrator
        ↓ persistence
Postgres (Neon) / Redis / ChromaDB
        ↓ enrich
OpenAI API + third-party integrations
```

The frontend (Next.js) communicates with FastAPI using Supabase-issued Bearer tokens. FastAPI routes forward long-running tasks—lead processing, proposal drafts, follow-ups—to Celery or the in-process workflow orchestrator. Persistent context lives in Postgres (core data), Redis (queues, realtime metrics), and ChromaDB (per-agent memory). OpenAI models power scoring, drafting, and optimization loops.

### Agent Communication
- `backend/orchestrator.py` coordinates the lead → proposal → follow-up pipeline.
- `backend/agents/lead_scoring.py` and `backend/agents/followups.py` exchange structured payloads with the orchestrator, pulling context from vector memory and feedback loops.
- `backend/agents/proposal_gen.py` incorporates branding prompts and memory entries to produce tailored proposals.

### Data Flow
1. **Lead Scoring**
   - POST `/leads` → FastAPI enqueues workflow.
   - Workflow pulls recent memory, calls `lead_scoring.score`, persists RunHistory + vector memory.
2. **Proposal Generation**
   - Workflow fetches lead, Supabase branding, vector memory.
   - `proposal_gen.draft_with_context` merges tone tokens and optimized prompts.
   - Proposal stored in Postgres; analytics snapshot recomputed.
3. **Feedback Loop**
   - POST `/feedback` stores qualitative feedback, updates vector memory, and fuels the reward optimizer.
   - `/self_optimize` and `/optimize` read aggregated KPI + feedback data to propose new prompts.

### Scaling Strategy
- **Multi-Agent Planner**: DAG orchestration (`backend/orchestrator/graph.py`) supports branching, parallel agents, and future multi-tenant scheduling.
- **Workers & Queues**: Celery with Redis broker scales horizontally for Gmail polling, email delivery, and analytics recomputation.
- **Memory & Embeddings**: ChromaDB persisted under `data/memory/chroma` enables per-agent recall without heavy infrastructure.

### Monitoring
- **Analytics Dashboard**: `/dashboard/analytics` surfaces conversion KPIs, revenue, and live metrics streamed from Redis.
- **Run History**: `/runs` renders agent latency, success, and cost, feeding into weekly self-optimization.
- **Branding & Marketing**: `/branding/*` endpoints expose asset health, tone tokens, and campaign templates for marketing automation.

### Deployment
- **Docker Compose**: `infra/docker-compose.yml` spins up API, worker, Postgres, Redis, and frontend for local or single-node hosting.
- **Render**: Suggested target for API, worker, and Postgres (Neon-compatible) with scheduled self-optimization jobs.
- **Vercel**: Deploy the Next.js frontend, connecting to Render-hosted API via environment variables.

For visual diagrams, reference:
- `infra/docker-compose.yml` for container topology.
- `docs/api_reference.md` for endpoint mappings across services.
