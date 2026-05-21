"""PubMed E-utilities connector.

Fetches recent PubMed abstracts and feeds them into the ingestion pipeline.
Respects NCBI rate limit: ≤3 requests/second unauthenticated.

Environment variables:
  PUBMED_QUERY         — default "longevity aging clinical trial"
  PUBMED_MAX_RESULTS   — default 10 per poll
  PUBMED_POLL_INTERVAL — default 1800 (30 minutes)
  NCBI_API_KEY         — optional, raises rate limit to 10 req/s

Run standalone:
  python -m services.ingestion.pubmed
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_BASE_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_BASE_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_MIN_DELAY = 0.34  # 3 req/s guardrail


def _get(url: str, params: dict) -> bytes:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(full_url, timeout=20) as resp:
        return resp.read()


def search_pmids(query: str, max_results: int = 10, api_key: str | None = None) -> list[str]:
    params: dict = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "pub+date",
    }
    if api_key:
        params["api_key"] = api_key
    data = json.loads(_get(_BASE_ESEARCH, params))
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_abstracts(pmids: list[str], api_key: str | None = None) -> list[dict]:
    """Fetch abstract + title for each PMID; returns list of dicts."""
    if not pmids:
        return []
    params: dict = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }
    if api_key:
        params["api_key"] = api_key
    time.sleep(_MIN_DELAY)
    xml_data = _get(_BASE_EFETCH, params)
    root = ET.fromstring(xml_data)
    results = []
    for article in root.iter("PubmedArticle"):
        pmid_el = article.find(".//PMID")
        title_el = article.find(".//ArticleTitle")
        abstract_el = article.find(".//AbstractText")
        pmid = pmid_el.text if pmid_el is not None else "unknown"
        title = title_el.text or "" if title_el is not None else ""
        abstract = abstract_el.text or "" if abstract_el is not None else ""
        if abstract:
            results.append({"pmid": pmid, "title": title, "abstract": abstract})
    return results


def run_polling_loop(pipeline, poll_interval: int | None = None) -> None:
    """Poll PubMed on a schedule and feed results into the ingestion pipeline."""
    from services.ingestion.pipeline import RawSignal

    query = os.getenv("PUBMED_QUERY", "longevity aging clinical trial")
    max_results = int(os.getenv("PUBMED_MAX_RESULTS", "10"))
    interval = poll_interval or int(os.getenv("PUBMED_POLL_INTERVAL", "1800"))
    api_key = os.getenv("NCBI_API_KEY")
    backoff = interval

    logger.info("PubMed polling started (query=%r, interval=%ds)", query, interval)
    while True:
        try:
            pmids = search_pmids(query, max_results, api_key)
            time.sleep(_MIN_DELAY)
            abstracts = fetch_abstracts(pmids, api_key)
            for item in abstracts:
                text = f"{item['title']}\n\n{item['abstract']}"
                signal = RawSignal(
                    source="pubmed",
                    source_url=f"https://pubmed.ncbi.nlm.nih.gov/{item['pmid']}/",
                    raw_text=text,
                    topics=["pubmed", "research"],
                )
                result = pipeline.ingest(signal)
                if result:
                    logger.info("PubMed signal ingested: PMID %s", item["pmid"])
            backoff = interval
        except Exception as exc:
            logger.warning("PubMed poll error: %s – backing off %ds", exc, backoff)
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
