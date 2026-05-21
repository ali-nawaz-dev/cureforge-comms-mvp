# Secrets And Access Guide

We set up all routine configuration. The client only provides private credentials, account access, and business approvals that cannot be generated safely by the implementation team.

---

## Implementation-Owned Setup (We Handle This)

- `.env.example` with all variable names and safe defaults
- Docker and Compose wiring
- CI configuration (GitHub Actions)
- Local Postgres and Redis defaults
- Redis bus stub and factory
- Webhook route structure (`/webhooks/resend/inbound`)
- Polling intervals and backoff logic
- Sandbox / test send modes
- Mocked tests and synthetic demo data
- Structured JSON logging

---

## Client-Provided Items

Request each item at least **12 hours** before the implementation stage needs it.

| Need by | Item | Request from | Notes |
|---|---|---|---|
| Morning of Day 4 | Resend API key + sender mailbox + sandbox test inbox address + inbound webhook secret | Oleg / Amine | DNS already handled by Amine — do not change DNS or Resend dashboard settings |
| Morning of Day 3 | Anthropic API key | Oleg | For matching rationale and outreach drafting |
| Day 1–2 if needed | Project-scoped Groq API key | Oleg | Optional if own Groq key is used early |
| Day 6 if ClickUp subscriber is built | ClickUp API token + `signal_intake` list ID | Oleg | Subscriber writes to staging list only; never to the main roadmap board |
| Day 7 | Taxonomy discrepancy resolution — confirm whether count is 56 or 57 and provide the missing entry if 57 is correct | Oleg | See taxonomy note below |

Secrets must be placed only in the deployment environment. **Never commit them to the repository.**

---

## Environment Variables — Complete Reference

Copy `.env.example` to `.env` and fill in the values below.

### Core Runtime

| Variable | Where to get it | Default | Required? |
|---|---|---|---|
| `DATABASE_URL` | Your Postgres host settings | `postgresql://cureforge:cureforge@localhost:5432/cureforge` | Optional — in-memory fallback if not set |
| `REDIS_URL` | Your Redis host settings | `redis://localhost:6379/0` | Optional — InMemoryBus fallback if not set |
| `BUS_BACKEND` | Set `redis` to use Redis; anything else uses InMemoryBus | `memory` | Optional |
| `LEDGER_SQLITE_PATH` | Local file path | `.local/ledger.sqlite3` | Optional — in-memory if not set |
| `KG_SQLITE_PATH` | Local file path | `.local/kg.sqlite3` | Optional — in-memory if not set |
| `LOG_LEVEL` | — | `INFO` | Optional |

### LLM Providers

Routing by layer:
- **Layer 1 parsing** → Groq + LLaMA 3.3 70B (`PARSER_LLM_PROVIDER=groq`)
- **Layer 2 rationale + Layer 3A drafting** → GPT-4o (`RATIONALE_LLM_PROVIDER=openai`, `DRAFTING_LLM_PROVIDER=openai`)
- **Default / tests** → Mock (no key required)

| Variable | Where to get it | Default | Required? |
|---|---|---|---|
| `LLM_PROVIDER` | — | `mock` | Optional — global fallback: `mock` / `groq` / `openai` / `anthropic` |
| `PARSER_LLM_PROVIDER` | — | `groq` | Optional — overrides `LLM_PROVIDER` for Layer 1 |
| `RATIONALE_LLM_PROVIDER` | — | `openai` | Optional — overrides `LLM_PROVIDER` for Layer 2 |
| `DRAFTING_LLM_PROVIDER` | — | `openai` | Optional — overrides `LLM_PROVIDER` for Layer 3A |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) → API Keys | (empty) | Required when `PARSER_LLM_PROVIDER=groq` — request from Oleg |
| `GROQ_MODEL` | Groq model list | `llama-3.3-70b-versatile` | Optional |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) → API Keys | (empty) | Required when `RATIONALE_LLM_PROVIDER=openai` — request from Oleg (Day 3) |
| `OPENAI_MODEL` | OpenAI model list | `gpt-4o` | Optional |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys | (empty) | Future phase — not active default |
| `ANTHROPIC_MODEL` | Anthropic model list | `claude-3-5-sonnet-latest` | Future phase |

### Outreach / Resend

| Variable | Where to get it | Default | Required? |
|---|---|---|---|
| `OUTREACH_SEND_MODE` | — | `sandbox` | Optional — `sandbox` / `live`. **Do not set `live` without client sign-off.** |
| `RESEND_API_KEY` | [resend.com](https://resend.com) → API Keys | (empty) | Required for real sandbox sends |
| `RESEND_FROM_EMAIL` | Resend verified sender | `outreach@contact.longevityintime.org` | Required for real sends — verified domain is `contact.longevityintime.org`, not the root domain |
| `RESEND_REPLY_TO` | — | `replies@contact.longevityintime.org` | Optional |
| `RESEND_SANDBOX_TO` | Your test inbox address | (empty) | Required in `sandbox` mode — all sends are redirected here |
| `RESEND_WEBHOOK_SECRET` | Resend → Webhooks → Signing secret | (empty) | Required when inbound webhook is live |

### Telegram

| Variable | Where to get it | Default | Required? |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather on Telegram (`/newbot`) | (empty) | Required for Telegram ingestion and notifications |
| `TELEGRAM_NOTIFY_CHAT_ID` | Use `getUpdates` API or `@userinfobot` | (empty) | Required for `meeting_requested` notifications |
| `TELEGRAM_POLL_INTERVAL` | — | `300` (5 min) | Optional |

### PubMed / NCBI

| Variable | Where to get it | Default | Required? |
|---|---|---|---|
| `PUBMED_QUERY` | — | `longevity aging clinical trial` | Optional |
| `PUBMED_MAX_RESULTS` | — | `10` | Optional |
| `PUBMED_POLL_INTERVAL` | — | `1800` (30 min) | Optional |
| `NCBI_API_KEY` | [NCBI API Key page](https://www.ncbi.nlm.nih.gov/account/) | (empty) | Optional — raises rate limit from 3 to 10 req/s |

### ClinicalTrials.gov

| Variable | Where to get it | Default | Required? |
|---|---|---|---|
| `CT_QUERY` | — | `longevity aging` | Optional |
| `CT_MAX_RESULTS` | — | `10` | Optional |
| `CT_POLL_INTERVAL` | — | `3600` (60 min) | Optional |

### ClickUp

| Variable | Where to get it | Default | Required? |
|---|---|---|---|
| `CLICKUP_API_TOKEN` | ClickUp → Settings → Apps → API Token | (empty) | Required for ClickUp subscriber |
| `CLICKUP_SIGNAL_INTAKE_LIST_ID` | ClickUp → List URL → extract list ID | (empty) | Required — staging list only, never the main roadmap |

---

## Source Repo Integration Approach

**Confirmed approach (updated):** Wrap both repos as packages with a clean boundary before merging into the monorepo. This gives clearer separation and avoids polluting the existing module tree.

| Repo | Owner | Location in monorepo | Wrap approach |
|---|---|---|---|
| `github.com/arshiefatima/longevity-multi-agent` | Arshie | `packages/ingestion_agent/` | Wrap as a package; keep Telegram polling and article parsing; remove `SalesInvestorAgent`, CSV-triggered outreach, per-article letter generation |
| `github.com/ali-nawaz-dev/cureforge-comms-mvp` | Ali | `packages/comms_agent/` | Wrap as a package; extract Layer 3A outreach drafting logic; discard any autonomous send paths |

**Steps when repos are available:**
1. Clone each repo into a temp directory.
2. Create `packages/ingestion_agent/` and `packages/comms_agent/` with `__init__.py`.
3. Copy relevant source files in; update internal imports.
4. Add each package to `[tool.setuptools.packages.find]` include list in `pyproject.toml`.
5. Wire the package entry points into `services/ingestion/` and `services/outreach/` callers.
6. Run `pytest` — all existing tests must still pass before adding new ones.

**Not this week:** A full package refactor with versioned releases, separate `pyproject.toml` per package, or PyPI publishing. Those are Phase 2 tasks.

## LLM Safety Constraints (Non-Negotiable)

- LLMs never compute match ranking — only write plain-English rationale.
- `INVESTOR_NDA` milestone body text is **redacted** before any LLM prompt is constructed.
- `INTERNAL_ONLY` milestones are rejected before reaching Layer 2 and never sent to LLMs.
- `INTERNAL_ONLY` confidentiality produces no outreach candidates.

---

## Taxonomy Note

Client metadata declares **57 total entities** (55 institutes + 2 sub-institutes). The current `data/taxonomy_v0_2.json` contains **56 entries**. Pending Oleg's confirmation of the missing entry, the loader tracks both counts without failing. Once confirmed:

1. Add the missing entry to `data/taxonomy_v0_2.json`.
2. Update the test in `tests/test_taxonomy.py` to match the confirmed count.
3. Tick off the taxonomy item in `docs/HANDOFF_CHECKLIST.md`.

---

## What Not To Touch

- Do not change DNS records for `longevityintime.org` — Amine owns this.
- Do not change Resend sender configuration in the Resend dashboard — Amine owns this.
- Do not commit any file containing real API keys, tokens, or passwords.
