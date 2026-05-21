from services.ingestion.pipeline import RawSignal


def telegram_signal(text: str, source_url: str = "telegram://demo") -> RawSignal:
    return RawSignal(source="telegram", source_url=source_url, raw_text=text, topics=["telegram"])


def pubmed_signal(title: str, abstract: str, pmid: str = "demo") -> RawSignal:
    return RawSignal(
        source="pubmed",
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        raw_text=f"{title}\n{abstract}",
        topics=["pubmed", "clinical"],
    )


def clinical_trials_signal(title: str, nct_id: str = "NCT00000000") -> RawSignal:
    return RawSignal(
        source="clinicaltrials_gov",
        source_url=f"https://clinicaltrials.gov/study/{nct_id}",
        raw_text=title,
        topics=["clinical_trial"],
    )

