import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

NameStatus = Literal["CONFIRMED", "VERIFY_CICL", "RESOLVE"]


@dataclass(frozen=True)
class Institute:
    institute_id: str
    tier_id: int
    tier_name: str
    long_name: str | None
    short_name: str | None
    name_status: NameStatus
    patent_anchor: str | None = None
    is_sub_institute: bool = False
    parent_institute_id: str | None = None

    @property
    def suppress_outreach(self) -> bool:
        return self.name_status == "RESOLVE"


@dataclass(frozen=True)
class Taxonomy:
    schema_version: str
    declared_total_entities: int
    institutes: dict[str, Institute]

    def get(self, institute_id: str) -> Institute:
        return self.institutes[str(institute_id)]

    def get_optional(self, institute_id: str) -> Institute | None:
        return self.institutes.get(str(institute_id))

    def is_resolve_pending(self, institute_id: str) -> bool:
        institute = self.get_optional(institute_id)
        return bool(institute and institute.suppress_outreach)

    def parent_for_matching(self, institute_id: str, rollup_sub_institutes: bool = False) -> str:
        """Return the institute id used for matching, rolling up sub-institutes.

        Unknown institute ids pass through unchanged so the matching layer can
        return a clean "no overlap" rather than raising on user-supplied data.
        """
        institute = self.get_optional(institute_id)
        if institute is None:
            return str(institute_id)
        if rollup_sub_institutes and institute.parent_institute_id:
            return institute.parent_institute_id
        return institute.institute_id


class TaxonomySchemaError(ValueError):
    """Raised when the taxonomy seed file fails validation."""


def load_taxonomy(path: str | Path) -> Taxonomy:
    """Load and validate a taxonomy JSON file.

    Validation rules (matches what the rest of the system relies on):

    - ``id_type`` must be ``"string"`` – we treat institute ids as strings.
    - Every institute must declare ``institute_id`` and ``name_status``.
    - ``parent_institute_id``, if present, must refer to a known institute.
    - ``declared_total_entities`` is exposed for the dashboard handoff card
      but does NOT have to equal ``len(institutes)`` – the README documents
      the gap. We just log when they differ.
    """
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise TaxonomySchemaError(f"taxonomy is not valid JSON: {exc}") from exc

    if data.get("id_type") != "string":
        raise TaxonomySchemaError("Taxonomy id_type must be 'string'")

    institutes: dict[str, Institute] = {}
    for tier in data.get("tiers", []):
        for raw in tier.get("institutes", []):
            institute = _parse_institute(raw, tier)
            if institute.institute_id in institutes:
                raise TaxonomySchemaError(
                    f"duplicate institute_id in taxonomy: {institute.institute_id}"
                )
            institutes[institute.institute_id] = institute

    if not institutes:
        raise TaxonomySchemaError("taxonomy must define at least one institute")

    for institute in institutes.values():
        if institute.parent_institute_id and institute.parent_institute_id not in institutes:
            raise TaxonomySchemaError(
                f"institute {institute.institute_id} references unknown parent "
                f"{institute.parent_institute_id}"
            )

    return Taxonomy(
        schema_version=data["schema_version"],
        declared_total_entities=data["federation_count"]["total_entities"],
        institutes=institutes,
    )


def _parse_institute(raw: dict[str, Any], tier: dict[str, Any]) -> Institute:
    institute_id = str(raw["institute_id"])
    name_status = raw["name_status"]
    if name_status not in {"CONFIRMED", "VERIFY_CICL", "RESOLVE"}:
        raise ValueError(f"Unsupported name_status: {name_status}")

    return Institute(
        institute_id=institute_id,
        tier_id=int(tier["tier_id"]),
        tier_name=tier["tier_name"],
        long_name=raw.get("long_name"),
        short_name=raw.get("short_name"),
        name_status=name_status,
        patent_anchor=raw.get("patent_anchor"),
        is_sub_institute=bool(raw.get("is_sub_institute", False)),
        parent_institute_id=raw.get("parent_institute_id"),
    )

