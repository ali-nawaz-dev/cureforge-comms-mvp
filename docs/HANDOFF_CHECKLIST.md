# Handoff Checklist

Sign-off date: 2026-05-19  
Signed off by: Ali Nawaz (implementation)

---

## Core Quality Gates

- [x] Tests pass locally (`pytest` — 70+ tests, 0 failures)
- [x] Lint passes (`ruff check .`)
- [x] CI passes on push (unit job + integration job via `docker-compose.test.yml`)
- [x] `.env.example` is current and documents every env var with source instructions

## Security And Safety

- [x] No secrets are committed to the repository
- [x] Resend remains sandbox/mock — `OUTREACH_SEND_MODE=sandbox` default enforced
- [x] Real specialist portal sends raise `NotImplementedError` (all six agents tested)
- [x] `INVESTOR_NDA` body text is redacted before every LLM call (`redact_for_llm()` tested)
- [x] `INTERNAL_ONLY` milestones do not reach matching (hard-filtered in `engine.py`)
- [x] DNS and Resend dashboard configuration untouched (Amine owns this)

## Data Integrity

- [x] Taxonomy v0.2 is loaded from `data/taxonomy_v0_2.json` (not hardcoded)
- [ ] **PENDING CLIENT CONFIRMATION** — Taxonomy count discrepancy: client metadata declares 57 entities, extracted JSON contains 56. Requires Oleg to confirm the missing entry or lower the declared count. See `NEXT_STEPS.md` → Watch Items.
- [x] Synthetic contacts are labeled `source_provenance.seed_source: "SYNTHETIC_DEMO"` (all 25 records)
- [x] Synthetic reviewers are clearly named `mock_*@longevityintime.org`

## Architecture And Documentation

- [x] Architecture evolution is documented (`docs/ARCHITECTURE_EVOLUTION.md`)
- [x] Specialist agent portal compliance status documented (`docs/SPECIALIST_AGENT_STATUS.md`)
- [x] Non-developer guide written with step-by-step tab instructions (`docs/NON_DEVELOPER_GUIDE.md`)
- [x] Secrets runbook complete with exact env var names and where each value comes from (`docs/SECRETS_AND_ACCESS.md`)
- [x] Gap closure report added to `NEXT_STEPS.md` covering all original items as Done / Partial / Deferred
- [x] README updated to reflect what is implemented, what is stubbed, and what is explicitly non-scope

## Implementation Completeness

- [x] Postgres repositories implemented (signals, contacts, matching runs, candidates, approvals, replies)
- [x] Redis bus implemented with InMemoryBus fallback (`BUS_BACKEND` env var)
- [x] SQLite ledger persisted and chain-verifiable (visible in dashboard Handoff tab)
- [x] SQLite KG stub with nodes and edges persisted
- [x] Telegram polling connector implemented (requires `TELEGRAM_BOT_TOKEN`)
- [x] PubMed NCBI E-utilities connector implemented
- [x] ClinicalTrials.gov API v2 connector implemented
- [x] NDA redaction enforced in ingestion pipeline and matching engine
- [x] Per-contact-type scorers implemented (Investor, GrantOfficer, KOL, Partner, DataCustodian)
- [x] Milestone publisher CLI runnable as `python -m services.matching.milestones`
- [x] Contact import CLI runnable as `python -m services.matching.cli_import`
- [x] Resend sandbox HTTP client implemented (`services/outreach/resend_client.py`)
- [x] Resend inbound webhook implemented (`services/outreach/webhook.py`)
- [x] `meeting_requested` Telegram notification implemented
- [x] Postgres-backed cooldown check implemented (falls back to in-memory)
- [x] All six specialist agents bus-subscribed and ledger-logging
- [x] Wrong-role rejection tested per agent using loaded `reviewers.json` identities
- [x] ClickUp subscriber implemented (`services/ingestion/clickup_subscriber.py`)
- [x] `docker-compose.yml` updated with healthchecks
- [x] `docker-compose.test.yml` created for integration test job
- [x] Streamlit dashboard: ledger verification panel in Handoff tab
- [x] Streamlit dashboard: reviewers loaded on startup, bus wired to matching engine

## Pending Client Actions Before Production

| Item | Owner | Status | Blocker for |
|---|---|---|---|
| Confirm taxonomy count (56 vs 57) and provide missing entry if 57 is correct | Oleg | ⏳ Pending | Test sign-off |
| Resend API key | Oleg / Amine | ✅ Received — paste into `.env` | Real sandbox sends |
| Resend domain `contact.longevityintime.org` verified + sending enabled | Amine | ✅ Confirmed | Outbound sends |
| Resend inbound MX routing active | Amine | ⚠️ In progress — hold live reply test | Live reply loop |
| Resend webhook secret | Amine | ⏳ Pending | Webhook signature verification |
| Resend sandbox test inbox address | Team | ⏳ Pending — fill `RESEND_SANDBOX_TO` in `.env` | Sandbox send redirect |
| Real reviewer identities (5 roles) | Boss via Oleg | ⏳ Expected Day 1 — swap into `reviewers.json` | Role-enforced approvals with real identities |
| OpenAI API key (GPT-4o) | Oleg | ⏳ Expected Day 3 — fill `OPENAI_API_KEY` | Real LLM rationale and drafting |
| Groq API key | Oleg | ⏳ Optional Day 1–2 — fill `GROQ_API_KEY` | Real LLM parsing |
| Telegram bot token + notify chat ID | Oleg | ⏳ Coming — not blocking Day 1 | Telegram ingestion + meeting notifications |
| Confirm `active_conversation_token` semantics | Oleg | ⏳ By Day 3 | Token TTL / refresh rule finalisation |
| Confirm/patch `[name pending]` taxonomy entries | Boss | ⏳ By Day 2 | Canonical taxonomy names |
| ClickUp API token + `signal_intake` list ID | Oleg | ⏳ Day 6 if subscriber built | ClickUp task creation |
| Confirm real outreach stays disabled until sign-off | Oleg | ✅ Confirmed — sandbox only throughout week one | Final production go-ahead |
