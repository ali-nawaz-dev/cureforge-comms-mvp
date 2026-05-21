-- Core schema – idempotent via IF NOT EXISTS guards.
-- Schema is the single source of truth: application code must not run DDL.

-- ---------------------------------------------------------------------------
-- Helper triggers and enums
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
  CREATE TYPE contact_type AS ENUM (
    'INVESTOR',
    'GRANT_OFFICER',
    'KOL',
    'PARTNER',
    'DATA_CUSTODIAN'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE approval_state AS ENUM (
    'DRAFTED',
    'AWAITING_APPROVAL',
    'APPROVED',
    'REJECTED',
    'EDITED',
    'SENT'
  );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Signals
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
  signal_id     UUID PRIMARY KEY,
  topic         TEXT NOT NULL,
  source        TEXT NOT NULL,
  content_hash  CHAR(64) NOT NULL UNIQUE,
  raw_text      TEXT,
  event_json    JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals (created_at DESC);

-- ---------------------------------------------------------------------------
-- Contacts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
  contact_id                  UUID PRIMARY KEY,
  contact_type                contact_type NOT NULL,
  name                        TEXT NOT NULL,
  organization                TEXT,
  role                        TEXT,
  focus_areas                 TEXT[] NOT NULL DEFAULT '{}',
  stated_thesis_tags          TEXT[] NOT NULL DEFAULT '{}',
  under_nda                   BOOLEAN NOT NULL DEFAULT FALSE,
  disinterest_flag            BOOLEAN NOT NULL DEFAULT FALSE,
  active_conversation_token   TEXT,
  last_contact_from_us_date   DATE,
  warm_signal_score           INTEGER NOT NULL DEFAULT 0 CHECK (warm_signal_score BETWEEN 0 AND 100),
  source_provenance           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contacts_last_contact_date
  ON contacts (last_contact_from_us_date);

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
  BEFORE UPDATE ON contacts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Matching runs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matching_runs (
  matching_run_id       UUID PRIMARY KEY,
  triggering_event_id   UUID NOT NULL REFERENCES signals(signal_id),
  triggering_topic      TEXT NOT NULL,
  scoring_config        JSONB NOT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_matching_runs_triggering_event
  ON matching_runs (triggering_event_id);

-- ---------------------------------------------------------------------------
-- Outreach candidates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outreach_candidates (
  candidate_id            UUID PRIMARY KEY,
  matching_run_id         UUID NOT NULL REFERENCES matching_runs(matching_run_id),
  contact_id              UUID NOT NULL REFERENCES contacts(contact_id),
  triggering_event_id     UUID NOT NULL REFERENCES signals(signal_id),
  match_score             DOUBLE PRECISION NOT NULL,
  match_rationale         TEXT NOT NULL,
  suggested_message_angle TEXT,
  suggested_channel       TEXT,
  confidence              DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  suppressed_reason       TEXT,
  provenance_hash         CHAR(64),
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_outreach_candidates_matching_run
  ON outreach_candidates (matching_run_id);

-- ---------------------------------------------------------------------------
-- Approval records (one row per draft)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approval_records (
  approval_id       UUID PRIMARY KEY,
  draft_id          UUID NOT NULL UNIQUE,
  state             approval_state NOT NULL,
  reviewer_identity TEXT,
  reviewer_role     TEXT,
  token_hash        CHAR(64),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approval_records_draft ON approval_records (draft_id);

DROP TRIGGER IF EXISTS trg_approval_records_updated_at ON approval_records;
CREATE TRIGGER trg_approval_records_updated_at
  BEFORE UPDATE ON approval_records
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Bridge table for multi-role HITL drafts. Each row is a required role; the
-- approval is complete only when an approver from every role has signed off.
CREATE TABLE IF NOT EXISTS approval_required_roles (
  draft_id   UUID NOT NULL,
  role       TEXT NOT NULL,
  approved   BOOLEAN NOT NULL DEFAULT FALSE,
  approved_by TEXT,
  approved_at TIMESTAMPTZ,
  PRIMARY KEY (draft_id, role),
  FOREIGN KEY (draft_id) REFERENCES approval_records(draft_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Replies
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS replies (
  reply_id      UUID PRIMARY KEY,
  candidate_id  UUID REFERENCES outreach_candidates(candidate_id),
  from_email    TEXT,
  body          TEXT,
  intent        TEXT,
  raw_payload   JSONB NOT NULL DEFAULT '{}',
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_replies_candidate_id ON replies (candidate_id);

-- ---------------------------------------------------------------------------
-- Webhook event dedup (out-of-process replay protection)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS webhook_events_seen (
  event_id    TEXT PRIMARY KEY,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
