# Non-Developer Guide — CureForge Comms MVP Dashboard

This guide explains how to use the dashboard as a non-technical user. No coding is required.

---

## Opening the Dashboard

1. Ask the technical team to start the dashboard, or run this command in the project folder:
   ```
   python3.11 -m streamlit run apps/dashboard/app.py
   ```
2. A browser window will open automatically at `http://localhost:8501`.
3. You will see a page titled **CureForge Comms MVP Dashboard**.

---

## The Dashboard Tabs

The dashboard has seven tabs across the top. Each one shows a different part of the workflow.

---

### Tab 1 — Signal Intake

**What it does:** Lets you enter or upload a new signal (a piece of research news or intelligence) and push it through the pipeline.

**Steps:**
1. Type a short description of the signal in the **Signal Text** box — for example:  
   *"New longevity aging clinical trial for stem cell regeneration published."*
2. Or click **Upload Signal File** to upload a `.txt`, `.md`, or `.csv` file.
3. Click **Ingest Signal**.
4. The system will deduplicate, filter, and classify the signal against the CureForge taxonomy.
5. A summary card will appear showing:
   - **Source** — where the signal came from
   - **Mapped Institute** — which taxonomy entry it matched
   - **Parser Confidence** — how confident the system is
   - **Summary** — a plain-English description of the signal
6. If the signal is a duplicate or not relevant to longevity, you will see a yellow notice.

---

### Tab 2 — Contacts & Matching

**What it does:** Shows which contacts in the relationship database are a good match for the signal you just ingested.

**Steps:**
1. After ingesting a signal in Tab 1, click **Run Matching** on this tab.
2. A ranked table of contacts will appear showing:
   - **Name** and **Organisation**
   - **Contact Type** (Investor, Grant Officer, KOL, Partner, Data Custodian)
   - **Match Score** — a number between 0 and 1; higher is better
   - **Rationale** — a plain-English explanation of why this contact is relevant
   - **Status** — whether the contact is available or suppressed (e.g. inside the 60-day cooldown)
3. Suppressed contacts show the reason, for example *cooldown_60_days* or *taxonomy_resolve_pending*.

> **Important:** The system scores contacts using fixed rules — the AI only writes the plain-English explanation. It does not decide who gets contacted.

---

### Tab 3 — Approval Queue

**What it does:** Lets a reviewer see, approve, or reject an outreach draft before anything is sent.

**Steps:**
1. Select a contact from the match results in Tab 2 and click **Create Draft**.
2. The draft email body will appear in this tab, prefixed with the reviewer role required.
3. Choose a reviewer identity from the dropdown (these are the seeded reviewer accounts).
4. Click **Approve** to issue an approval token, or **Reject** to discard the draft.
5. If the wrong reviewer role is selected, the system will refuse with a *PermissionError* — this is intentional and enforced by code, not just the UI.
6. Once approved, an **Approval Token** badge will appear showing the reviewer name and role.

> **Nothing can be sent without a valid approval token issued by the correct role.** This is enforced at the code level.

---

### Tab 4 — Outreach

**What it does:** Sends the approved draft to a sandbox test inbox (never to real external recipients during MVP).

**Steps:**
1. With an approved draft in Tab 3, switch to the Outreach tab.
2. Click **Send (Sandbox)**.
3. A confirmation card will show:
   - **Provider:** Resend
   - **Mode:** Sandbox
   - **Result:** Delivered in sandbox
4. A blue info banner confirms that no real external outreach was sent.
5. A simulated reply panel lets you type a reply text and click **Classify Reply** to see the intent:
   - `meeting_requested` — triggers a Telegram notification (if configured)
   - `not_interested` — records disinterest
   - `needs_review` — sent for manual review

---

### Tab 5 — Specialist Agents

**What it does:** Lets you route a request to one of the six specialist drafting agents.

**The six agents are:**
- **Grant Agent** — Grants.gov applications (requires `grants_administrator` approval)
- **Preprint Agent** — arXiv submissions (requires `principal_investigator`)
- **Journal Agent** — Editorial Manager submissions (requires `principal_investigator`)
- **Patent Agent** — USPTO filings (requires `patent_counsel`)
- **DUA Agent** — Data Use Agreements (requires `regulatory_advisor` or `institutional_legal`)
- **FDA Agent** — FDA ESG submissions (requires `regulatory_advisor`)

**Steps:**
1. Select an agent from the dropdown.
2. Type or paste the request text.
3. Click **Create Specialist Draft**.
4. The draft will appear with the required `AI-DRAFTED — NOT FOR SUBMISSION WITHOUT [ROLE] REVIEW` header.
5. The draft enters the same approval queue as general outreach.
6. Real portal submission is **hard-disabled** for MVP — clicking the submit button will show a "Not Implemented" message. This is intentional.

---

### Tab 6 — Data & Safety

**What it does:** Shows system health metrics and lets you inspect safety data.

**What you will see:**
- **Taxonomy Loaded** — number of taxonomy entities loaded
- **Client Declared** — number the client's metadata declared (57); a yellow notice appears if these differ
- **Synthetic Contacts** — number of demo contacts in the session
- **Institute Browser** — click any institute to see its ID, name status, and tier
- **Suppression Audit** — shows any contacts or candidates that were suppressed and why

---

### Tab 7 — Handoff

**What it does:** Provides final sign-off materials for the client.

**What you will see:**
- **Handoff notes** — known limitations and confirmed safe behaviors
- **Provenance Ledger** — the last 10 records in the audit chain, each with a hash. A green badge means the chain is intact and unmodified.
- **Download Handoff Documents** — buttons to download the README, secrets guide, non-developer guide, specialist status doc, handoff checklist, and architecture evolution document.

---

## The Sidebar

The sidebar on the left has two sections.

### LLM Settings

Choose which AI model the system uses:
- **Mock** (default) — safe test mode, no API key needed, generates demo text
- **Groq** — fast; paste your Groq API key and choose model
- **Anthropic** — high quality; paste your Anthropic API key

Click **Apply LLM Settings** after changing. Your keys stay in this browser session only and are never saved or committed to the project.

### Data Uploads

Replace the demo taxonomy or contacts for this session:
- Upload a **Taxonomy JSON** file (must follow the v0.2 format)
- Upload a **Contacts JSON or CSV** file
- Click **Use Uploaded Taxonomy** or **Use Uploaded Contacts** to apply
- Click **Reset Demo Data** to go back to the synthetic defaults

---

## What Is Safe During MVP

| Action | Safe? | Notes |
|---|---|---|
| Ingest signals | Yes | Demo text or uploaded files |
| Run matching | Yes | Synthetic contacts only |
| Create and approve drafts | Yes | Synthetic reviewers only |
| Sandbox send | Yes | No real email is sent |
| Specialist drafts | Yes | Portal sends are disabled |
| Upload taxonomy or contacts | Yes | Session only, not saved |
| Enter API keys | Yes | Session only, not committed |

## What Is NOT Enabled

| Action | Status | What to do |
|---|---|---|
| Real external email | Disabled | Request Resend handoff from Oleg/Amine |
| Real Telegram ingestion | Disabled until token provided | Provide `TELEGRAM_BOT_TOKEN` in `.env` |
| Real portal submissions | Hard-disabled | Not available in MVP — by design |
| Production monitoring | Not built | Future phase |

---

## Getting Help

If you see an error or the dashboard behaves unexpectedly, note the tab you were on and what you clicked, then share the terminal output with the technical team. The most common issue is a missing `.env` file — copy `.env.example` to `.env` to fix it.
