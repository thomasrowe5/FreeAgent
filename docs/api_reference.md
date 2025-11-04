## API Reference

All endpoints require a Supabase JWT presented as a `Bearer` token in the `Authorization` header. Responses are JSON unless noted.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/leads` | `POST` / `GET` | Create a new lead with branded scoring, or list recent leads. |
| `/proposals` | `POST` | Generate a proposal for a given lead ID. |
| `/followups` | `POST` | Schedule follow-up tasks and update lead status. |
| `/analytics/summary` | `GET` | Return KPI snapshot, status breakdown, and revenue data. |
| `/self_optimize` | `POST` | Trigger the self-optimization loop, generate report + prompt drafts. |
| `/branding/assets` | `POST` / `GET` | Upload or fetch branding configuration for a user. |
| `/branding/proposal_pdf` | `POST` | Create a branded PDF proposal (requires reportlab). |
| `/branding/email_templates` | `POST` | Persist HTML campaign templates locally. |

### Authentication Header
```bash
-H "Authorization: Bearer $(supabase auth token)"
```

### Create Lead
```bash
curl -X POST http://localhost:8000/leads \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp",
    "email": "ceo@acme.com",
    "message": "We need an MVP in four weeks.",
    "value": 12000,
    "client_type": "startup"
  }'
```

### Generate Proposal
```bash
curl -X POST http://localhost:8000/proposals \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1}'
```

### Schedule Follow-up
```bash
curl -X POST http://localhost:8000/followups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1, "days_after": 3}'
```

### Analytics Snapshot
```bash
curl http://localhost:8000/analytics/summary \
  -H "Authorization: Bearer $TOKEN"
```

### Self Optimization Report
```bash
curl -X POST http://localhost:8000/self_optimize \
  -H "Authorization: Bearer $TOKEN"
```

### Branding Assets
```bash
curl -X POST http://localhost:8000/branding/assets \
  -H "Authorization: Bearer $TOKEN" \
  -F "user_id=demo" \
  -F 'brand_colors={"primary":"#2563eb","accent":"#f97316"}'
```

Additional endpoints (memory, integrations, orchestrator) follow similar patterns and honor the same Supabase-based authentication.
