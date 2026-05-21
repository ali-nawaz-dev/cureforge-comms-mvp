"""ClinicalTrials.gov API v2 connector.

Polls the ClinicalTrials.gov v2 REST API and feeds results into the ingestion
pipeline.

Environment variables:
  CT_QUERY           — search query, default "longevity aging"
  CT_MAX_RESULTS     — default 10 per poll
  CT_POLL_INTERVAL   — default 3600 (60 minutes)

Run standalone:
  python -m services.ingestion.clinicaltrials
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_BASE = "https://clinicaltrials.gov/api/v2/studies"


def search_studies(query: str, max_results: int = 10) -> list[dict]:
    params = {
        "query.term": query,
        "pageSize": max_results,
        "format": "json",
        "fields": "NCTId,BriefTitle,BriefSummary,Condition,Phase",
    }
    url = f"{_BASE}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read())
    return data.get("studies", [])


def _study_text(study: dict) -> tuple[str, str]:
    """Return (text_body, nct_id) from a study object."""
    proto = study.get("protocolSection", {})
    id_module = proto.get("identificationModule", {})
    desc_module = proto.get("descriptionModule", {})
    nct_id = id_module.get("nctId", "unknown")
    title = id_module.get("briefTitle", "")
    summary = desc_module.get("briefSummary", "")
    return f"{title}\n\n{summary}", nct_id


def run_polling_loop(pipeline, poll_interval: int | None = None) -> None:
    """Poll ClinicalTrials.gov and feed studies into the ingestion pipeline."""
    from services.ingestion.pipeline import RawSignal

    query = os.getenv("CT_QUERY", "longevity aging")
    max_results = int(os.getenv("CT_MAX_RESULTS", "10"))
    interval = poll_interval or int(os.getenv("CT_POLL_INTERVAL", "3600"))
    backoff = interval

    logger.info("ClinicalTrials.gov polling started (query=%r, interval=%ds)", query, interval)
    while True:
        try:
            studies = search_studies(query, max_results)
            for study in studies:
                text, nct_id = _study_text(study)
                if not text.strip():
                    continue
                signal = RawSignal(
                    source="clinicaltrials_gov",
                    source_url=f"https://clinicaltrials.gov/study/{nct_id}",
                    raw_text=text,
                    topics=["clinical_trial", "research"],
                )
                result = pipeline.ingest(signal)
                if result:
                    logger.info("ClinicalTrials signal ingested: %s", nct_id)
            backoff = interval
        except Exception as exc:
            logger.warning("ClinicalTrials poll error: %s – backing off %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 7200)
            continue
        time.sleep(interval)


if __name__ == "__main__":
    from packages.bus.factory import get_bus
    from packages.common.logging import configure_json_logging
    from packages.llm.factory import build_llm_client
    from packages.taxonomy import load_taxonomy
    from services.ingestion.pipeline import IngestionPipeline

    configure_json_logging()
    bus = get_bus()
    taxonomy = load_taxonomy()
    llm = build_llm_client()
    pipeline = IngestionPipeline(bus=bus, taxonomy=taxonomy, parser_llm=llm)
    run_polling_loop(pipeline)
