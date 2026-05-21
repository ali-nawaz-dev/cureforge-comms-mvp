import csv
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from packages.bus import get_bus
from packages.hitl import ApprovalQueue
from packages.llm import MockLLMClient
from packages.llm.http_clients import AnthropicLLMClient, GroqLLMClient, OpenAILLMClient
from packages.taxonomy import Taxonomy, load_taxonomy
from packages.taxonomy.loader import Institute
from services.ingestion import IngestionPipeline
from services.ingestion.pipeline import RawSignal
from services.ingestion.sources import telegram_signal
from services.matching import Contact, MatchingEngine
from services.matching.contacts import load_contacts
from services.matching.worker import MatcherWorker
from services.outreach import OutreachSender
from services.outreach.drafting import OutreachDraftingService
from services.outreach.worker import OutreachWorker
from services.specialists import specialist_agents
from services.specialists.agents import wire_all_agents


ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "data" / "taxonomy_v0_2.json"
CONTACTS_PATH = ROOT / "data" / "seeds" / "contacts.json"


def dashboard_views() -> list[str]:
    return [
        "ingestion_health",
        "contact_browser",
        "matching_audit",
        "approval_queue",
        "message_chain",
        "reply_intent_status",
        "suppression_reasons",
    ]


def build_demo_dashboard_data() -> dict[str, Any]:
    from packages.bus import InMemoryBus

    taxonomy = load_taxonomy(TAXONOMY_PATH)
    contacts = load_contacts(CONTACTS_PATH)
    bus = InMemoryBus()
    pipeline = IngestionPipeline(bus=bus, taxonomy=taxonomy)
    signal = pipeline.ingest(telegram_signal("Stem cell longevity clinical regenerative update"))
    matches = MatchingEngine(taxonomy=taxonomy, contacts=contacts).match_external_signal(signal) if signal else []

    queue = ApprovalQueue(bus=bus)
    draft = queue.draft("Demo outreach draft for HITL review.", {"principal_investigator"})
    token = queue.approve(draft.draft_id, "mock_pi@longevityintime.org", "principal_investigator")
    send_result = OutreachSender(queue).send_email(draft.draft_id, token)

    return {
        "taxonomy": taxonomy,
        "contacts": contacts,
        "published_events": bus.published,
        "matches": matches,
        "approval_record": queue.records[draft.draft_id],
        "send_result": send_result,
        "specialists": specialist_agents(),
    }


def render_dashboard() -> None:
    import streamlit as st

    st.set_page_config(page_title="CureForge Comms MVP", layout="wide")
    _inject_styles(st)
    _init_state(st)
    _render_llm_settings(st)
    _render_outreach_settings(st)
    _render_data_settings(st)

    st.title("CureForge Comms MVP Dashboard")
    st.caption(
        "A guided, non-technical interface for testing signal intake, matching, approvals, "
        "sandbox outreach, and specialist draft routing."
    )

    _render_status_cards(st)

    tabs = st.tabs(
        [
            "1. Intake Signal",
            "2. Match & Draft",
            "3. Approve & Send",
            "4. Specialist Drafts",
            "5. Data & Safety",
            "Handoff",
        ]
    )

    with tabs[0]:
        _render_intake_tab(st)

    with tabs[1]:
        _render_match_tab(st)

    with tabs[2]:
        _render_approval_tab(st)

    with tabs[3]:
        _render_specialists_tab(st)

    with tabs[4]:
        _render_data_safety_tab(st)

    with tabs[5]:
        _render_handoff_tab(st)


def _init_state(st: Any) -> None:
    if "taxonomy" in st.session_state:
        return
    from packages.hitl import load_reviewers
    from packages.ledger.chain import Ledger

    taxonomy = load_taxonomy(TAXONOMY_PATH)
    contacts = load_contacts(CONTACTS_PATH)
    bus = get_bus()
    queue = ApprovalQueue(bus=bus)
    reviewers = load_reviewers()
    ledger = Ledger()
    st.session_state.taxonomy = taxonomy
    st.session_state.contacts = contacts
    st.session_state.bus = bus
    st.session_state.parser_llm = MockLLMClient()
    st.session_state.rationale_llm = MockLLMClient()
    st.session_state.drafting_llm = MockLLMClient()
    st.session_state.parser_provider = "Mock"
    st.session_state.rationale_provider = "Mock"
    st.session_state.queue = queue
    st.session_state.reviewers = reviewers
    st.session_state.ledger = ledger
    st.session_state.current_event = None
    st.session_state.matches = []
    st.session_state.current_draft_id = None
    st.session_state.approval_token = None
    st.session_state.send_result = None
    st.session_state.specialist_drafts = []
    st.session_state.activity_log = []
    st.session_state.active_conversation_token = None
    st.session_state.resend_client = None
    st.session_state.resend_send_mode = "sandbox"
    st.session_state.draft_cache = {}
    _rebuild_pipeline(st)
    _rebuild_engine(st)
    # Bus spine: ingestion publishes external_signal.*, MatcherWorker
    # subscribes and produces validated outreach candidates, OutreachWorker
    # turns those into HITL drafts, and specialist agents listen for
    # specialist_request.* topics.
    st.session_state.matcher_worker = MatcherWorker(bus, st.session_state.engine, ledger=ledger)
    st.session_state.matcher_worker.start()
    st.session_state.outreach_worker = OutreachWorker(
        bus, queue, contacts, ledger=ledger
    )
    st.session_state.outreach_worker.start()
    st.session_state.specialists = wire_all_agents(bus, queue, ledger=ledger)


def _rebuild_pipeline(st: Any) -> None:
    """Single place that constructs the IngestionPipeline.

    Threads bus, taxonomy, and parser LLM consistently so callers can never
    drop one of them by accident.
    """
    st.session_state.pipeline = IngestionPipeline(
        bus=st.session_state.bus,
        taxonomy=st.session_state.taxonomy,
        parser_llm=st.session_state.parser_llm,
        ledger=st.session_state.get("ledger"),
    )


def _rebuild_engine(st: Any) -> None:
    """Single place that constructs the MatchingEngine.

    The engine does not publish directly: ``MatcherWorker`` owns the
    ``external_signal -> outreach_candidate`` publish step. The dashboard
    still calls ``engine.match_external_signal`` to populate the UI table,
    but those calls are read-only.
    """
    st.session_state.engine = MatchingEngine(
        taxonomy=st.session_state.taxonomy,
        contacts=st.session_state.contacts,
        rationale_llm=st.session_state.rationale_llm,
    )
    # Refresh the worker so it dispatches through the new engine.
    if "matcher_worker" in st.session_state:
        worker = st.session_state.matcher_worker
        worker._engine = st.session_state.engine
    if "outreach_worker" in st.session_state:
        worker = st.session_state.outreach_worker
        worker._contacts = {str(c.contact_id): c for c in st.session_state.contacts}


def _inject_styles(st: Any) -> None:
    st.markdown(
        """
        <style>
        .cf-card {
            border: 1px solid rgba(120, 120, 120, 0.25);
            border-radius: 16px;
            padding: 1rem;
            background: rgba(120, 120, 120, 0.06);
        }
        .cf-small {
            font-size: 0.9rem;
            opacity: 0.8;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_status_cards(st: Any) -> None:
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Taxonomy Loaded", len(st.session_state.taxonomy.institutes))
    col2.metric("Client Declared", st.session_state.taxonomy.declared_total_entities)
    col3.metric("Synthetic Contacts", len(st.session_state.contacts))
    col4.metric("Signals Published", len(st.session_state.bus.published))
    col5.metric("Candidate Matches", len(st.session_state.matches))

    parser = st.session_state.get("parser_provider", "Mock")
    rationale = st.session_state.get("rationale_provider", "Mock")
    # Show concise routing summary: Groq→Layer1, GPT-4o→L2+L3A
    llm_label = f"L1:{parser} / L2:{rationale}"
    col6.metric("LLM Routing", llm_label, help="L1=parsing (Groq), L2=rationale+drafting (OpenAI GPT-4o)")


def _render_llm_settings(st: Any) -> None:
    with st.sidebar:
        st.header("LLM Settings")
        st.caption(
            "Layer 1 parsing → Groq (LLaMA 3.3 70B) · "
            "Layer 2 rationale + drafting → OpenAI GPT-4o. "
            "Keys stay in this browser session only."
        )

        parser_provider = st.selectbox(
            "Parsing / signal summary LLM",
            ["Mock", "Groq", "OpenAI", "Anthropic"],
            index=["Mock", "Groq", "OpenAI", "Anthropic"].index(
                st.session_state.get("parser_provider", "Mock")
            ),
            help="Groq + LLaMA 3.3 70B confirmed for Layer 1 parsing.",
        )
        parser_key = st.text_input("Parsing API key", type="password")
        parser_model = st.text_input(
            "Parsing model",
            value="llama-3.3-70b-versatile" if parser_provider == "Groq" else "mock-safe-local",
        )

        rationale_provider = st.selectbox(
            "Rationale / outreach drafting LLM",
            ["Mock", "OpenAI", "Groq", "Anthropic"],
            index=["Mock", "OpenAI", "Groq", "Anthropic"].index(
                st.session_state.get("rationale_provider", "Mock")
            ),
            help="GPT-4o confirmed for Layer 2 rationale and Layer 3A drafting.",
        )
        rationale_key = st.text_input("Rationale/drafting API key", type="password")
        rationale_model = st.text_input(
            "Rationale/drafting model",
            value=(
                "gpt-4o"
                if rationale_provider == "OpenAI"
                else "claude-3-5-sonnet-latest"
                if rationale_provider == "Anthropic"
                else "mock-safe-local"
            ),
        )

        if st.button("Apply LLM Settings", use_container_width=True):
            try:
                parser_llm = _build_dashboard_llm(parser_provider, parser_key, parser_model)
                rationale_llm = _build_dashboard_llm(
                    rationale_provider, rationale_key, rationale_model
                )
            except ValueError as exc:
                st.error(str(exc))
                return

            st.session_state.parser_llm = parser_llm
            st.session_state.rationale_llm = rationale_llm
            st.session_state.drafting_llm = rationale_llm
            st.session_state.parser_provider = parser_provider
            st.session_state.rationale_provider = rationale_provider
            _rebuild_pipeline(st)
            _rebuild_engine(st)
            st.session_state.draft_cache = {}
            st.success("LLM settings applied for this session.")


def _render_outreach_settings(st: Any) -> None:
    with st.sidebar:
        st.header("Outreach Settings")
        st.caption(
            "Resend key stays in this browser session only. "
            "It is never written to any file or committed to the repo."
        )

        resend_key = st.text_input(
            "Resend API key",
            type="password",
            placeholder="re_...",
            key="resend_key_input",
            help="From resend.com → API Keys. Leave blank to use the key in .env (if set).",
        )
        sandbox_to = st.text_input(
            "Sandbox test inbox",
            placeholder="your-test@example.com",
            key="resend_sandbox_to_input",
            help=(
                "All sandbox sends are redirected here — real recipient never receives anything. "
                "Required when Resend key is set."
            ),
        )
        send_mode = st.selectbox(
            "Send mode",
            ["sandbox", "live"],
            index=0,
            key="resend_send_mode_input",
            help=(
                "sandbox → redirects to test inbox. "
                "live → sends to real recipient. "
                "Do NOT set live until client sign-off is confirmed."
            ),
        )

        if send_mode == "live":
            st.warning(
                "LIVE mode selected. Emails will reach real recipients. "
                "Only enable after client sign-off and DNS verification."
            )

        if st.button("Apply Outreach Settings", use_container_width=True):
            if resend_key and not sandbox_to and send_mode == "sandbox":
                st.error("Sandbox test inbox is required when a Resend key is provided.")
            else:
                from services.outreach.resend_client import ResendClient
                st.session_state.resend_client = ResendClient(
                    api_key=resend_key or None,
                    mode=send_mode,
                    sandbox_to=sandbox_to or None,
                )
                st.session_state.resend_send_mode = send_mode
                st.success(
                    f"Outreach settings applied — mode: {send_mode}. "
                    "Key is in session memory only."
                )


def _render_data_settings(st: Any) -> None:
    with st.sidebar:
        st.header("Data Uploads")
        st.caption("Replace demo data for this session. Nothing is saved to files.")

        taxonomy_file = st.file_uploader("Upload taxonomy JSON", type=["json"], key="taxonomy_upload")
        if taxonomy_file is not None and st.button("Use Uploaded Taxonomy", use_container_width=True):
            try:
                taxonomy = _taxonomy_from_uploaded_json(taxonomy_file)
                _replace_taxonomy_and_rebuild(st, taxonomy)
                st.success("Taxonomy loaded for this session.")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                st.error(f"Could not load taxonomy: {exc}")

        contacts_file = st.file_uploader(
            "Upload contacts JSON or CSV", type=["json", "csv"], key="contacts_upload"
        )
        if contacts_file is not None and st.button("Use Uploaded Contacts", use_container_width=True):
            try:
                contacts = _contacts_from_uploaded_file(contacts_file)
                _replace_contacts_and_rebuild(st, contacts)
                st.success("Contacts loaded for this session.")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                st.error(f"Could not load contacts: {exc}")

        if st.button("Reset Demo Data", use_container_width=True):
            taxonomy = load_taxonomy(TAXONOMY_PATH)
            contacts = load_contacts(CONTACTS_PATH)
            _replace_taxonomy_and_rebuild(st, taxonomy)
            _replace_contacts_and_rebuild(st, contacts)
            st.success("Demo taxonomy and contacts restored.")


def _build_dashboard_llm(provider: str, api_key: str, model: str) -> Any:
    if provider == "Mock":
        return MockLLMClient()
    if not api_key:
        raise ValueError(f"{provider} requires an API key.")
    if provider == "Groq":
        return GroqLLMClient(api_key=api_key, model=model)
    if provider == "OpenAI":
        return OpenAILLMClient(api_key=api_key, model=model)
    if provider == "Anthropic":
        return AnthropicLLMClient(api_key=api_key, model=model)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def _replace_taxonomy_and_rebuild(st: Any, taxonomy: Taxonomy) -> None:
    st.session_state.taxonomy = taxonomy
    _rebuild_pipeline(st)
    _rebuild_engine(st)
    st.session_state.matches = []
    st.session_state.current_event = None
    st.session_state.draft_cache = {}
    st.session_state.activity_log.append("Taxonomy data replaced for this session.")


def _replace_contacts_and_rebuild(st: Any, contacts: list[Contact]) -> None:
    st.session_state.contacts = contacts
    _rebuild_engine(st)
    st.session_state.matches = []
    st.session_state.draft_cache = {}
    st.session_state.activity_log.append("Contact data replaced for this session.")


def _taxonomy_from_uploaded_json(uploaded_file: Any) -> Taxonomy:
    data = json.loads(uploaded_file.getvalue().decode("utf-8"))
    if data.get("id_type") != "string":
        raise ValueError("taxonomy id_type must be string")

    institutes: dict[str, Institute] = {}
    for tier in data["tiers"]:
        for raw in tier["institutes"]:
            institute = Institute(
                institute_id=str(raw["institute_id"]),
                tier_id=int(tier["tier_id"]),
                tier_name=tier["tier_name"],
                long_name=raw.get("long_name"),
                short_name=raw.get("short_name"),
                name_status=raw["name_status"],
                patent_anchor=raw.get("patent_anchor"),
                is_sub_institute=bool(raw.get("is_sub_institute", False)),
                parent_institute_id=raw.get("parent_institute_id"),
            )
            institutes[institute.institute_id] = institute
    return Taxonomy(
        schema_version=data["schema_version"],
        declared_total_entities=data["federation_count"]["total_entities"],
        institutes=institutes,
    )


def _contacts_from_uploaded_file(uploaded_file: Any) -> list[Contact]:
    raw_text = uploaded_file.getvalue().decode("utf-8")
    if uploaded_file.name.lower().endswith(".json"):
        rows = json.loads(raw_text)
    else:
        rows = list(csv.DictReader(raw_text.splitlines()))
    return [_contact_from_row(row) for row in rows]


def _contact_from_row(row: dict[str, Any]) -> Contact:
    focus_areas = _list_field(row.get("focus_areas", []))
    thesis_tags = _list_field(row.get("stated_thesis_tags", []))
    source_provenance = row.get("source_provenance") or {"seed_source": "CLIENT_UPLOAD"}
    if isinstance(source_provenance, str):
        try:
            source_provenance = json.loads(source_provenance)
        except json.JSONDecodeError:
            source_provenance = {"seed_source": source_provenance}
    return Contact(
        contact_id=row.get("contact_id") or uuid4(),
        contact_type=row["contact_type"],
        name=row["name"],
        organization=row.get("organization", ""),
        focus_areas=focus_areas,
        stated_thesis_tags=thesis_tags,
        warm_signal_score=int(row.get("warm_signal_score", 50)),
        under_nda=_bool_field(row.get("under_nda", False)),
        disinterest_flag=_bool_field(row.get("disinterest_flag", False)),
        last_contact_from_us_date=row.get("last_contact_from_us_date") or None,
        active_conversation_token=row.get("active_conversation_token") or None,
        source_provenance=source_provenance,
    )


def _list_field(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]


def _bool_field(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes", "y"}


def _render_intake_tab(st: Any) -> None:
    st.subheader("Step 1: Add An External Signal")
    st.write(
        "Paste a signal or upload a simple document. The MVP analyzes it locally and runs the "
        "same matching workflow without needing live client integrations."
    )

    input_mode = st.radio("How do you want to add information?", ["Paste text", "Upload document"])

    if input_mode == "Paste text":
        with st.form("signal_form"):
            source = st.selectbox("Signal source", ["telegram", "pubmed", "clinicaltrials_gov"])
            text = st.text_area(
                "Signal text",
                value="Stem cell longevity clinical regenerative update from a new study.",
                height=140,
                help="Use plain English. The demo classifier will map it to a CureForge institute.",
            )
            source_url = st.text_input("Source URL", value=f"{source}://demo")
            topics_text = st.text_input("Topics", value="longevity, clinical, regenerative")
            submitted = st.form_submit_button("Analyze Signal", type="primary")

        if submitted:
            topics = [topic.strip() for topic in topics_text.split(",") if topic.strip()]
            signal = RawSignal(source=source, source_url=source_url, raw_text=text, topics=topics)
            _process_uploaded_or_pasted_signal(st, signal)
    else:
        uploaded = st.file_uploader(
            "Upload a document",
            type=["txt", "md", "csv"],
            help="MVP supports text, markdown, and CSV locally. PDF/DOCX can be added later.",
        )
        topics_text = st.text_input("Topics for uploaded document", value="longevity, client-upload")
        if uploaded is not None:
            extracted_text = _extract_uploaded_text(uploaded)
            st.markdown("### Document Preview")
            st.text_area("Extracted text", value=extracted_text[:3000], height=180, disabled=True)
            if st.button("Analyze Uploaded Document", type="primary"):
                topics = [topic.strip() for topic in topics_text.split(",") if topic.strip()]
                signal = RawSignal(
                    source="telegram",
                    source_url=f"client_upload://{uuid4()}/{uploaded.name}",
                    raw_text=extracted_text,
                    topics=topics,
                )
                _process_uploaded_or_pasted_signal(st, signal, label="Uploaded document")

    st.divider()
    st.subheader("Published Signal Events")
    _event_table(st)


def _process_uploaded_or_pasted_signal(st: Any, signal: RawSignal, label: str = "Signal") -> None:
    event = st.session_state.pipeline.ingest(signal)
    if event is None:
        st.warning(f"{label} was filtered out or detected as a duplicate.")
        st.session_state.activity_log.append(f"{label} filtered or deduplicated.")
        return

    st.session_state.current_event = event
    st.session_state.matches = st.session_state.engine.match_external_signal(event)
    st.session_state.activity_log.append(f"{label} published to external_signal.{signal.source}.")
    st.success(f"{label} accepted, classified, and published to the internal bus.")
    _signal_summary(st, event)


def _extract_uploaded_text(uploaded_file: Any) -> str:
    """Decode an uploaded file to plain text.

    CSV uploads are flattened into a human-readable preview rather than
    being mangled by a comma-replace, which used to destroy CSV structure.
    """
    raw = uploaded_file.getvalue()
    text = raw.decode("utf-8", errors="replace")
    if uploaded_file.name.lower().endswith(".csv"):
        rows = list(csv.reader(text.splitlines()))
        return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows if row)
    return text


def _render_match_tab(st: Any) -> None:
    st.subheader("Step 2: Review Matches And Create A Draft")
    if not st.session_state.matches:
        st.info("No matches yet. Start by analyzing a signal in Step 1.")
        return

    _matches_table(st)
    actionable = [match for match in st.session_state.matches if match.suppressed_reason is None]
    if not actionable:
        st.warning("All matches are suppressed. Review suppression reasons in Data & Safety.")
        return

    labels = [
        f"{idx + 1}. {match.contact.name} - {match.contact.organization} "
        f"(score {match.match_score:.2f})"
        for idx, match in enumerate(actionable)
    ]
    selected = st.selectbox("Choose a candidate to draft outreach for", labels)
    selected_match = actionable[labels.index(selected)]

    cache = st.session_state.setdefault("draft_cache", {})
    cache_key = str(getattr(selected_match, "candidate_id", id(selected_match)))
    regen = st.button("Regenerate draft", help="Re-run the drafting LLM for this candidate")
    if regen or cache_key not in cache:
        cache[cache_key] = OutreachDraftingService(
            st.session_state.drafting_llm
        ).draft_email(selected_match)
    default_draft = cache[cache_key]
    draft_text = st.text_area("Draft message", value=default_draft, height=180, key=f"draft_text_{cache_key}")
    if st.button("Create Draft For Approval", type="primary"):
        record = st.session_state.queue.draft(draft_text, {"principal_investigator"})
        st.session_state.current_draft_id = record.draft_id
        st.session_state.approval_token = None
        st.session_state.send_result = None
        st.session_state.activity_log.append("Outreach draft created and sent to approval queue.")
        st.success("Draft created. Go to Step 3 to approve and sandbox-send it.")


def _render_approval_tab(st: Any) -> None:
    st.subheader("Step 3: Approve And Sandbox Send")
    draft_id = st.session_state.current_draft_id
    if draft_id is None:
        st.info("No draft yet. Create one from a candidate in Step 2.")
        return

    record = st.session_state.queue.records[draft_id]
    st.markdown("### Current Draft")
    st.code(record.content)
    _approval_summary(st, record)

    reviewers = st.session_state.get("reviewers", [])
    reviewer_options = (
        [f"{r.email}  [{r.role}]" for r in reviewers]
        if reviewers
        else [
            "mock_pi@longevityintime.org  [principal_investigator]",
            "mock_grants_admin@longevityintime.org  [grants_administrator]",
            "mock_patent_counsel@longevityintime.org  [patent_counsel]",
            "mock_regulatory_advisor@longevityintime.org  [regulatory_advisor]",
            "mock_institutional_legal@longevityintime.org  [institutional_legal]",
        ]
    )
    selected_reviewer = st.selectbox("Reviewer account", reviewer_options)
    # Parse email and role from "email  [role]" format
    if "  [" in selected_reviewer:
        reviewer = selected_reviewer.split("  [")[0].strip()
        role = selected_reviewer.split("  [")[1].rstrip("]").strip()
    else:
        reviewer = selected_reviewer
        role = st.selectbox(
            "Reviewer role (manual)",
            ["principal_investigator", "patent_counsel", "regulatory_advisor",
             "institutional_legal", "grants_administrator"],
        )

    col1, col2 = st.columns(2)
    if col1.button("Approve Draft", type="primary"):
        try:
            token = st.session_state.queue.approve(draft_id, reviewer, role)
            st.session_state.approval_token = token
            st.session_state.activity_log.append(f"Draft approved by {reviewer}.")
            st.success("Approved. The sandbox send button is now available.")
        except (PermissionError, ValueError) as exc:
            st.error(str(exc))

    if col2.button("Send In Sandbox"):
        try:
            resend_client = st.session_state.get("resend_client")
            result = OutreachSender(
                st.session_state.queue,
                resend_client=resend_client,
                ledger=st.session_state.get("ledger"),
            ).send_email(
                draft_id, st.session_state.approval_token
            )
            st.session_state.send_result = result
            st.session_state.activity_log.append("Sandbox send completed.")
            st.success("Sandbox send completed. No real outreach was sent.")
        except (PermissionError, ValueError) as exc:
            st.error(str(exc))

    if st.session_state.send_result:
        st.markdown("### Send Output")
        _send_summary(st, st.session_state.send_result)
        st.caption("From: outreach@contact.longevityintime.org (verified Resend subdomain)")

        st.divider()
        st.markdown("### Simulate Inbound Reply")
        st.caption(
            "Inbound MX routing is being configured by Amine. "
            "Use this panel to test reply intent classification and conversation token lifecycle."
        )
        reply_text = st.text_area(
            "Paste or type a reply",
            value="Thank you for reaching out. I'd love to schedule a meeting to discuss further.",
            height=100,
            key="reply_sim_text",
        )
        if st.button("Classify Reply Intent", key="classify_reply_btn"):
            sender = OutreachSender(st.session_state.queue)
            current_token = st.session_state.get("active_conversation_token")
            intent, new_token = sender.handle_inbound_reply(
                text=reply_text,
                from_email="simulated-reply@example.com",
                contact_name="Simulated Contact",
                draft_id=str(draft_id),
                current_token=current_token,
            )
            st.session_state.active_conversation_token = new_token
            st.session_state.activity_log.append(f"Reply classified as: {intent}")

            intent_colours = {
                "meeting_requested": "success",
                "not_interested": "error",
                "needs_review": "warning",
                "interested": "success",
                "needs_info": "info",
            }
            intent_labels = {
                "meeting_requested": "Meeting Requested — Telegram notification sent (if configured)",
                "not_interested": "Not Interested — conversation token revoked",
                "needs_review": "Needs Review — flagged for human inspection",
                "interested": "Interested — conversation token issued/refreshed",
                "needs_info": "Needs More Info — conversation token issued/refreshed",
            }
            label = intent_labels.get(intent, intent)
            colour = intent_colours.get(intent, "info")
            getattr(st, colour)(f"Intent: **{label}**")

            st.markdown("#### Conversation Token Status")
            col_t1, col_t2 = st.columns(2)
            from packages.hitl.conversation_token import is_token_valid, token_expiry
            if new_token and is_token_valid(new_token):
                expires = token_expiry(new_token) or "unknown"
                col_t1.success("Token Active")
                col_t2.caption(f"Expires: {expires} — bypasses 60-day cooldown in matching")
            elif new_token is None and current_token is not None:
                col_t1.error("Token Revoked")
                col_t2.caption("60-day cooldown now applies to this contact")
            else:
                col_t1.info("No Token")
                col_t2.caption("60-day cooldown applies")


def _render_specialists_tab(st: Any) -> None:
    st.subheader("Step 4: Create A Specialist Draft")
    agents = specialist_agents()
    agent_by_name = {agent.name: agent for agent in agents}
    agent_name = st.selectbox("Specialist agent", list(agent_by_name))
    request = st.text_area(
        "Draft request",
        value="Prepare a short, AI-drafted specialist package for human review.",
        height=120,
    )

    if st.button("Create Specialist Draft", type="primary"):
        agent = agent_by_name[agent_name]
        draft_id = agent.draft(request, st.session_state.queue, ledger=st.session_state.get("ledger"))
        st.session_state.specialist_drafts.append({"agent": agent, "draft_id": draft_id})
        st.session_state.activity_log.append(f"{agent.name} draft created.")
        st.success("Specialist draft created and placed in the approval queue.")

    st.markdown("### Specialist Agent Status")
    st.dataframe(
        [
            {
                "agent": agent.name,
                "topic": agent.topic,
                "required_roles": ", ".join(sorted(agent.required_roles)),
                "real_portal_send": "Hard-disabled for MVP",
            }
            for agent in agents
        ],
        use_container_width=True,
    )

    if st.button("Prove Real Portal Sends Are Disabled"):
        agent = agent_by_name[agent_name]
        try:
            agent.submit_to_real_portal(payload={"demo": True})
        except NotImplementedError as exc:
            st.success(str(exc))


def _render_data_safety_tab(st: Any) -> None:
    st.subheader("Step 5: Inspect Data And Safety Rules")
    view = st.radio("Choose a view", ["Contacts", "Taxonomy", "Suppressions", "Activity Log"])

    if view == "Contacts":
        _contacts_table(st)
    elif view == "Taxonomy":
        query = st.text_input("Find institute by ID", value="34-AaD")
        if query:
            try:
                institute = st.session_state.taxonomy.get(query)
                _institute_summary(st, institute)
            except KeyError:
                st.error("Institute ID not found.")
    elif view == "Suppressions":
        _matches_table(st, suppressed_only=True)
    else:
        st.write(st.session_state.activity_log or ["No activity yet."])


def _render_handoff_tab(st: Any) -> None:
    st.subheader("Handoff Notes")
    st.info(
        "Client metadata declares 57 taxonomy entities, while the extracted taxonomy JSON "
        "currently contains 56 entries. This is documented for client review."
    )
    st.markdown(
        "- No secrets are committed.\n"
        "- Resend remains sandbox/mock until handoff.\n"
        "- Real specialist portal sends raise `NotImplementedError`.\n"
        "- `INVESTOR_NDA` text is redacted before LLM calls.\n"
        "- This MVP demonstrates workflow behavior with synthetic contacts and reviewers."
    )

    # Ledger verification panel
    st.markdown("### Provenance Ledger")
    ledger = st.session_state.get("ledger")
    if ledger is None:
        from packages.ledger.chain import Ledger
        ledger = Ledger()
        st.session_state["ledger"] = ledger

    is_valid = ledger.verify_chain()
    if is_valid:
        st.success(f"Ledger chain verified. {len(ledger.records)} record(s) intact.")
    else:
        st.error("Ledger chain verification FAILED — possible tampering detected.")

    last_records = ledger.last_n(10)
    if last_records:
        st.dataframe(
            [
                {
                    "record_id": r.record_id,
                    "record_type": r.record_type,
                    "chain_hash": r.chain_hash[:16] + "...",
                    "timestamp": r.timestamp,
                }
                for r in reversed(last_records)
            ],
            use_container_width=True,
        )

    st.markdown("### Download Handoff Documents")
    st.write("Use these files for client review, internal handoff, or non-technical walkthroughs.")
    _download_document_grid(st)


def _event_table(st: Any) -> None:
    st.dataframe(
        [
            {
                "topic": event.topic,
                "event_id": str(event.event_id),
                "provenance_hash": event.provenance_hash,
            }
            for event in st.session_state.bus.published
        ],
        use_container_width=True,
    )


def _download_document_grid(st: Any) -> None:
    documents = [
        ("Client README", ROOT / "README.md"),
        ("Next Steps", ROOT / "NEXT_STEPS.md"),
        ("Secrets And Access Guide", ROOT / "docs" / "SECRETS_AND_ACCESS.md"),
        ("Specialist Agent Status", ROOT / "docs" / "SPECIALIST_AGENT_STATUS.md"),
        ("Non-Developer Guide", ROOT / "docs" / "NON_DEVELOPER_GUIDE.md"),
        ("Handoff Checklist", ROOT / "docs" / "HANDOFF_CHECKLIST.md"),
        ("Architecture Evolution", ROOT / "docs" / "ARCHITECTURE_EVOLUTION.md"),
    ]
    for row_start in range(0, len(documents), 2):
        columns = st.columns(2)
        for column, (label, path) in zip(columns, documents[row_start : row_start + 2], strict=False):
            if path.exists():
                column.download_button(
                    label=f"Download {label}",
                    data=path.read_text(),
                    file_name=path.name,
                    mime="text/markdown",
                    use_container_width=True,
                )
            else:
                column.warning(f"{label} is not available yet.")


def _signal_summary(st: Any, event: Any) -> None:
    st.markdown("### Signal Summary")
    institute_labels = [
        f"{item.institute_id} ({round(item.confidence * 100)}% confidence)"
        for item in event.institutes
    ]
    col1, col2, col3 = st.columns(3)
    col1.metric("Source", event.source.replace("_", " ").title())
    col2.metric("Mapped Institute", ", ".join(institute_labels))
    col3.metric("Parser Confidence", f"{round(event.parser_confidence * 100)}%")
    st.write("**Summary:**", event.parsed_summary)
    st.write("**Topics:**", ", ".join(event.topics) if event.topics else "None provided")
    st.write("**Source link:**", event.source_url)
    st.caption(f"Audit hash: {event.provenance_hash}")


def _approval_summary(st: Any, record: Any) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Approval Status", record.state.value)
    col2.metric("Required Role", ", ".join(sorted(record.required_roles)))
    col3.metric("Approval Token", "Issued" if record.token else "Not issued")
    st.caption("Only a reviewer with the required role can approve this draft.")


def _send_summary(st: Any, result: Any) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Provider", result.provider.title())
    col2.metric("Mode", result.mode.title())
    col3.metric("Result", "Delivered in sandbox" if result.delivered else "Not delivered")
    st.info("This is a sandbox send only. No real external outreach was sent.")


def _institute_summary(st: Any, institute: Any) -> None:
    display_name = institute.long_name or "Name pending"
    col1, col2 = st.columns(2)
    col1.metric("Institute ID", institute.institute_id)
    col2.metric("Name Status", institute.name_status.replace("_", " ").title())
    st.write("**Long name:**", display_name)
    st.write("**Short name:**", institute.short_name or "Not available yet")
    st.write("**Tier:**", f"{institute.tier_id} - {institute.tier_name}")
    st.write("**Patent anchor:**", institute.patent_anchor or "None")
    if institute.is_sub_institute:
        st.write("**Sub-institute of:**", institute.parent_institute_id)
    if institute.suppress_outreach:
        st.warning("This institute is marked RESOLVE, so outreach candidates are suppressed.")


def _contacts_table(st: Any) -> None:
    st.dataframe(
        [
            {
                "name": contact.name,
                "type": contact.contact_type,
                "organization": contact.organization,
                "focus_areas": ", ".join(contact.focus_areas),
                "warm_signal": contact.warm_signal_score,
                "under_nda": contact.under_nda,
                "seed_source": contact.source_provenance["seed_source"],
            }
            for contact in st.session_state.contacts
        ],
        use_container_width=True,
    )


def _matches_table(st: Any, suppressed_only: bool = False) -> None:
    matches = st.session_state.matches
    if suppressed_only:
        matches = [match for match in matches if match.suppressed_reason]
    st.dataframe(
        [
            {
                "candidate_id": str(match.candidate_id),
                "contact": match.contact.name,
                "organization": match.contact.organization,
                "score": round(match.match_score, 3),
                "suppressed_reason": match.suppressed_reason,
                "rationale": match.match_rationale,
            }
            for match in matches[:20]
        ],
        use_container_width=True,
    )


if __name__ == "__main__":
    render_dashboard()

