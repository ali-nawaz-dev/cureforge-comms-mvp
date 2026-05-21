import json
from pathlib import Path
from uuid import UUID

from services.matching.engine import Contact


def load_contacts(path: str | Path) -> list[Contact]:
    data = json.loads(Path(path).read_text())
    return [
        Contact(
            contact_id=UUID(row["contact_id"]),
            contact_type=row["contact_type"],
            name=row["name"],
            organization=row["organization"],
            focus_areas=row["focus_areas"],
            stated_thesis_tags=row["stated_thesis_tags"],
            warm_signal_score=row["warm_signal_score"],
            under_nda=row.get("under_nda", False),
            disinterest_flag=row.get("disinterest_flag", False),
            last_contact_from_us_date=row.get("last_contact_from_us_date"),
            active_conversation_token=row.get("active_conversation_token"),
            source_provenance=row["source_provenance"],
        )
        for row in data
    ]

