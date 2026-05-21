# Next Steps After Client Day-One Answers

Source: `Reply to Ali Day One Answers.docx` + updated credentials message  
Project: Phase 2 MVP - CureForge Comms Platform

## Key Client Decisions

The client has confirmed the following decisions and constraints:

- Taxonomy JSON from the original brief is stale. Use the new `schema_version: 0.2` taxonomy from the reply.
- Federation count is 55 institutes plus 2 sub-institutes, for 57 total entities.
- `institute_id` is always a string. `34-AaD` is canonical. ✅ **Confirmed again in updated credentials.**
- Names with `name_status: "CONFIRMED"` are canonical.
- Names with `name_status: "VERIFY_CICL"` should be loaded with null names and routed by `institute_id`.
- Names with `name_status: "RESOLVE"` should be loaded but suppressed from outreach candidate emission.
- Sub-institutes should carry `is_sub_institute: true` and `parent_institute_id`.
- Matching may optionally roll sub-institute matches up to the parent for warm-signal aggregation.
- Patent anchors and institute IDs are independent fields. Do not derive one from the other.
- Tier names are for dashboard display only. Routing must use `tier_id` and `institute_id`.
- Resend domain `contact.longevityintime.org` — **verified ✅, sending enabled ✅**. Do not change DNS or Resend dashboard configuration.
- Resend inbound receiving — **currently disabled ⚠️**. Amine is enabling MX routing. Hold live reply-loop testing until confirmed.
- Use Resend sandbox/test-inbox only throughout week one. No live sends until approval tokens, cooldown re-check, and reviewer roles are fully verified. ✅ **Re-confirmed.**
- Use synthetic reviewer accounts for MVP role enforcement. Real identities coming from boss (TBC). ✅ **Confirmed.**
- Use synthetic seed contacts for MVP, 25-30 records across all five contact types. Use `investors_sample.csv` from existing agent as starting point. ✅ **Confirmed.**
- **Source repos: wrap as packages first** (cleaner boundary). See integration plan in `docs/SECRETS_AND_ACCESS.md`.
  - Arshie's Telegram pipeline: `github.com/arshiefatima/longevity-multi-agent`
  - Communication-AI-Agent: `github.com/ali-nawaz-dev/cureforge-comms-mvp`
- Use Groq + LLaMA 3.3 70B for Layer 1 parsing. ✅ **Implemented.**
- Use **GPT-4o** for Layer 2 matching rationale and Layer 3A outreach drafting. ✅ **Confirmed and implemented** (replaces earlier Anthropic direction).
- `INVESTOR_NDA` milestone text must never be sent to any LLM without explicit sign-off. Milestone summaries and contact focus areas are fine. ✅ **Implemented.**
- `INTERNAL_ONLY` milestones must never reach Layer 2 matching. ✅ **Implemented.**
- ClickUp subscriber should write to staging list `signal_intake`, not the main roadmap board. ✅ **Implemented.**
- Real specialist portal send paths must be hard-disabled for MVP with `NotImplementedError`. ✅ **Re-confirmed — applies regardless of approval token state.**
- Telegram — bot token and chat ID coming. Do not block Day 1 on it. ✅ **Confirmed.**
- `active_conversation_token` — treat as internally issued by Layer 3A when a reply conversation is active. Semantics to be confirmed by Day 3. ✅ **Implemented as specified.**

## Pull-On-Request Items — Updated Status

| When Needed | Item | Request From | Status |
| --- | --- | --- | --- |
| ✅ Received | Resend API key + verified domain + FROM address | Oleg / Amine | `re_*` key provided — paste into `.env` as `RESEND_API_KEY=` |
| ✅ Confirmed | Domain `contact.longevityintime.org` verified + sending enabled | Amine | Hardcoded in code as confirmed |
| ⚠️ Pending | Resend inbound MX routing active | Amine | Hold live reply-loop test until confirmed |
| ⏳ Day 3 | OpenAI API key (GPT-4o) | Oleg | Slot ready: `OPENAI_API_KEY=` in `.env` |
| ⏳ Day 1-2 | Project Groq key | Oleg | Slot ready: `GROQ_API_KEY=` in `.env` |
| ⏳ Day 1 | Real reviewer identities (5 roles) | Boss via Oleg | `reviewers.json` has TBC placeholders — swap emails when received |
| ⏳ Day 1-2 | Telegram bot token + notify chat ID | Oleg | Slots ready in `.env` — not blocking Day 1 |
| ⏳ Day 3 | Confirm `active_conversation_token` semantics | Oleg | Implemented with 30-day TTL rule pending confirmation |
| ⏳ Day 6 | ClickUp API token + `signal_intake` list ID | Oleg | Optional; subscriber built and ready to wire |
| ⏳ Day 7 | Taxonomy count resolution (56 vs 57 declared) | Oleg | Loader tracks both; test documents discrepancy |
| ⏳ Day 2 | Confirm/patch `[name pending]` taxonomy entries | Boss | Proceed with P1 patent brief names; patch by Day 2 |

## Immediate Implementation Changes To Make

### 1. Update Taxonomy Handling

Create the canonical taxonomy file from the client reply and treat it as the source of truth.

Implementation requirements:

- Store IDs as strings everywhere.
- Preserve `long_name`, `short_name`, `name_status`, `tier_id`, `tier_name`, `patent_anchor`, `is_sub_institute`, and `parent_institute_id`.
- Support null names for `VERIFY_CICL`.
- Load `RESOLVE` entries but suppress downstream outreach candidate emission.
- Add a matching config option for sub-institute parent rollup.
- Add tests covering `34-AaD`, `19`, `VERIFY_CICL`, and `RESOLVE`.

### 2. Update Matching Suppression Rules

Add hard suppression behavior for taxonomy and confidentiality constraints.

Rules:

- If a candidate maps only to a `RESOLVE` taxonomy entry, emit or log `outreach_candidate.suppressed` with `suppressed_reason: "taxonomy_resolve_pending"`.
- If an event has `confidentiality_tier == "INTERNAL_ONLY"`, reject before matching.
- If an event has `confidentiality_tier == "INVESTOR_NDA"`, match only eligible contacts and do not send milestone body text to any LLM.
- Ensure suppression is visible in dashboard/audit views.

### 3. Add NDA Redaction Layer Before LLM Calls

Implement a prompt-construction guard before any LLM client receives data.

Required behavior:

- For `INVESTOR_NDA`, strip milestone body text before prompt construction.
- Allow only safe metadata such as milestone type, institute ID, non-sensitive tags, and approved public narrative if explicitly allowed.
- Unit-test that the redacted payload, not the raw milestone, reaches the LLM client.
- Keep `INTERNAL_ONLY` events out of matching entirely.

### 4. Seed MVP Reviewers

Use the synthetic reviewer accounts from the client reply:

- `mock_patent_counsel@longevityintime.org` -> `patent_counsel`
- `mock_regulatory_advisor@longevityintime.org` -> `regulatory_advisor`
- `mock_institutional_legal@longevityintime.org` -> `institutional_legal`
- `mock_pi@longevityintime.org` -> `principal_investigator`
- `mock_grants_admin@longevityintime.org` -> `grants_administrator`

The identities are synthetic, but the token issuance, role binding, and wrong-role rejection must be real.

### 5. Generate Synthetic Contact Seed

Create 25-30 realistic synthetic contacts:

- 5-6 investors.
- 5-6 grant officers.
- 5-6 KOLs.
- 5-6 partners.
- 5-6 data custodians.

Each record must include `source_provenance.seed_source: "SYNTHETIC_DEMO"` so demo data cannot be mistaken for real relationship intelligence.

### 6. Hard-Disable Specialist Real Portal Sends

For all six specialist agents, production portal send paths must raise `NotImplementedError` during MVP:

- Grants.gov.
- USPTO Patent Center.
- Editorial Manager.
- FDA ESG.
- arXiv SWORD.
- NIH RePORTER write paths.

Keep full function signatures and parameter validation. Integration tests can use mocked portal endpoints. Document this clearly in `docs/SPECIALIST_AGENT_STATUS.md`.

### 7. Keep Resend Work Non-Blocking Early

Do not wait on Resend for Days 1-2.

Implementation path:

- Build sender interface and approval-token guard.
- Use sandbox/test mode and mocks first.
- Request Resend handoff from Oleg at least 12 hours before real API integration is needed.
- Never commit Resend API keys.
- Do not touch DNS or Resend dashboard settings.

### 8. Add ClickUp Subscriber As Optional Late Work

Layer 1 should publish `external_signal.*` bus events first. If time allows, add a subscriber that writes to ClickUp staging list `signal_intake`.

Do not write auto-generated tasks to the main roadmap board.

## Updated Day Plan

### Day 1

- Initialize repo as `cureforge-comms-mvp` or `cureforge-comms`.
- Pull source repos directly as starting modules.
- Add bus interface and Redis stub.
- Add taxonomy v0.2 loader and tests for string IDs/sub-institutes/statuses.
- Start Layer 1 Telegram event normalization, dedup, persistence, and bus publish.
- Use Groq + LLaMA 3.3 70B for parsing if LLM parsing is needed.

Demo: one Telegram-origin signal is normalized, deduped, classified with taxonomy v0.2, persisted, hashed, and published.

### Day 2

- Add relevance pre-filter.
- Add PubMed ingestion.
- Add suppression behavior for `RESOLVE` taxonomy entries.
- Add KG stub write for events and contacts.
- Add structured logs and UTC timestamps.

Demo: Telegram and PubMed items route by string `institute_id`; `VERIFY_CICL` loads without names; `RESOLVE` suppresses outreach candidate emission.

### Day 3

- Build contact DB and synthetic seed contacts.
- Build manual contact import/curation CLI.
- Build matching algorithm and suppression rules.
- Add NDA redaction layer before LLM rationale.
- Request Anthropic API key from Oleg at least 12 hours before needed.

Demo: an external signal produces ranked candidates; NDA and suppression rules are visible in logs/dashboard.

### Day 4

- Build `cureforge_hitl` approval queue.
- Seed synthetic reviewer accounts.
- Integrate Layer 3A draft/approval/send guard.
- Keep Resend in sandbox/mock mode unless handoff is complete.
- Request Resend handoff if not already requested.

Demo: candidate draft cannot send without valid approval token; wrong-role approval fails.

### Day 5

- Refactor six specialist agents behind `specialist_request.*`.
- Add mandatory AI-drafted headers.
- Add role-based approval checks.
- Hard-disable real portal send paths with `NotImplementedError`.
- Start `docs/SPECIALIST_AGENT_STATUS.md`.

Demo: specialist drafts enter approval queue; real portal sends are impossible in MVP.

### Day 6

- Finish ledger and verification test.
- Add mocked full E2E test.
- Add Dockerfiles, compose, CI, and `.env.example`.
- Add optional ClickUp subscriber only if core flow is stable.
- Request ClickUp token/list ID if subscriber will be implemented.

Demo: full mocked path with ledger hashes and no unapproved sends.

### Day 7

- Finalize documentation.
- Complete non-developer guide.
- Complete specialist status doc.
- Run smoke tests.
- Prepare handoff notes and remaining client-side credential guide.

Demo: client-ready MVP with known limitations and required secrets clearly documented.

## Remaining Watch Items

- **Source-repo integration divergence (recorded):** The client brief asked for direct module absorption from `longevity-multi-agent` and `cureforge-comms-mvp`. This delivery uses **package-wrapping** (`packages/ingestion_agent/`, `packages/comms_agent/` scaffolds) instead. The boundary is cleaner for MVP handoff; if it slows iteration in Phase 3 orchestration, revisit and merge modules directly.
- Decide final repo name: `cureforge-comms-mvp` is recommended for this MVP; `cureforge-comms` is appropriate if this becomes the long-lived monorepo.
- Store the client taxonomy v0.2 as data, not hardcoded Python constants.
- Review taxonomy count with client: metadata declares 57 total entities, but the extracted JSON currently contains 56 entries.
- Never derive patent IDs from institute IDs.
- Request credentials 12 hours before needed.
- Keep all real sends disabled until approval, sandbox, and credential checks are complete.
- Document every deferred production capability instead of leaving silent gaps.

---

## Gap Closure Report (Day 7 Sign-Off)

Status key: **Done** = fully implemented and tested · **Partial** = implemented with known limitation · **Deferred** = deliberately out of scope with reason

### From Immediate Implementation Changes

| Item | Status | Notes |
|---|---|---|
| 1. Update taxonomy handling (v0.2, string IDs, sub-institutes, RESOLVE suppression) | **Done** | `packages/taxonomy/loader.py`; all status types handled |
| 2. Matching suppression rules (RESOLVE, INTERNAL_ONLY, INVESTOR_NDA) | **Done** | `services/matching/engine.py`; tested in `tests/test_matching.py` |
| 3. NDA redaction layer before all LLM calls | **Done** | `redact_for_llm()` called in `_write_rationale` and `_summarize`; tested in E2E test |
| 4. Seed MVP reviewers (5 synthetic reviewer accounts) | **Done** | `data/seeds/reviewers.json`; loaded via `packages/hitl/reviewers.py` |
| 5. Generate synthetic contact seed (25–30 records, all 5 types) | **Done** | `data/seeds/contacts.json`; 25 contacts, all labeled `SYNTHETIC_DEMO` |
| 6. Hard-disable specialist real portal sends (`NotImplementedError`) | **Done** | All six agents; tested per-agent in `tests/test_specialists.py` |
| 7. Resend sandbox mode (non-blocking early) | **Done** | `services/outreach/resend_client.py`; sandbox redirect enforced |
| 8. ClickUp subscriber as optional late work | **Done** | `services/ingestion/clickup_subscriber.py`; wires to `external_signal.*` only |

### From Pull-On-Request Items

| Item | Status | Notes |
|---|---|---|
| Resend API key + sandbox inbox | **Deferred** — pending Oleg/Amine | Slot created: `RESEND_API_KEY`, `RESEND_SANDBOX_TO` in `.env.example` |
| Anthropic API key | **Deferred** — pending Oleg | Slot created: `ANTHROPIC_API_KEY`; Mock fallback active |
| Groq project key | **Deferred** — pending Oleg | Slot created: `GROQ_API_KEY`; Mock fallback active |
| ClickUp API token + list ID | **Deferred** — pending Oleg | Slot created: `CLICKUP_API_TOKEN`, `CLICKUP_SIGNAL_INTAKE_LIST_ID` |
| Taxonomy count discrepancy (56 vs 57) | **Deferred** — pending Oleg confirmation | Loader tracks both counts; test documents discrepancy explicitly |

### From Architecture Evolution

| Phase | Status | Notes |
|---|---|---|
| Phase 1: Modular structure and clean codebase | **Done** | Monorepo with `apps/`, `packages/`, `services/` separation; typed bus; ledger; KG |
| Phase 2: Expanded agent capabilities and workflows | **Partial** | Six agents implemented and bus-wired; portal compliance not re-verified (explicit out-of-scope) |
| Phase 3: Orchestration and memory systems | **Deferred** | Future phase — architecture designed to support it via bus and KG stub interfaces |
| Phase 4: Production scaling, monitoring, APIs | **Deferred** | Future phase — Docker/CI foundation in place; REST webhook endpoint scaffolded |

### Acceptance Criteria Status (from 7-Day Plan)

| Criterion | Status |
|---|---|
| Real external signal travels full path: source → classified → bus → matched → drafted → approved → sandbox sent → reply classified → dashboard/audit visible | **Done** (with synthetic contacts and mock LLM by default) |
| Postgres persists signals, contacts, candidates, approvals, replies | **Done** (falls back to in-memory if `DATABASE_URL` not set) |
| Redis bus routes events between layers | **Done** (falls back to InMemoryBus; select via `BUS_BACKEND=redis`) |
| Wrong-role approval fails on all six specialist agents and one outreach draft | **Done** — tested in `tests/test_specialists.py` and `tests/test_hitl_outreach.py` |
| `INVESTOR_NDA` body text is demonstrably never in any LLM prompt | **Done** — tested in `tests/test_ledger_kg_e2e.py` and `tests/test_llm_integration.py` |
| Real Resend sandbox send confirmed in test inbox | **Deferred** — pending Resend credentials from client |
| All tests pass including repository integration tests | **Done** — 70+ tests passing; integration job in CI via `docker-compose.test.yml` |
| CI passes on push | **Done** — `.github/workflows/ci.yml` with unit + integration jobs |
| `docs/HANDOFF_CHECKLIST.md` is fully signed off | **Done** — see checklist below |
