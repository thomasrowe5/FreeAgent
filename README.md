# FreeAgent: AI Ops Manager for Freelancers

## How to Run Locally

1. **Install prerequisites**
   - Python 3.11+
   - Node.js 20+
   - Redis & Postgres (or use Docker Compose below)

2. **Clone & install dependencies**
   ```bash
   git clone https://github.com/your-org/freeagent.git
   cd freeagent
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cd frontend && npm install && cd ..
   ```

3. **Environment variables**
   - Copy `.env.example` → `.env` and fill in API keys (Supabase, OpenAI, Google, Stripe, Sentry, etc.).
   - Export `NEXT_PUBLIC_API_URL` for the frontend.

4. **Run services**
   ```bash
   docker compose -f infra/docker-compose.yml up --build
   ```
   This launches Postgres, Redis, FastAPI API, Celery worker, and Next.js frontend.

5. **Seed demo data (optional)**
   ```bash
   source .venv/bin/activate
   python scripts/seed_demo_data.py
   ```

6. **Visit the app**
   - Frontend: http://localhost:3000 (landing page at `/landing`, dashboard at `/dashboard`).
   - API docs: http://localhost:8000/docs

## Project Scripts
- `scripts/seed_demo_data.py`: populate demo leads and proposals
- `scripts/demo_outline.txt`: Loom video talking points
