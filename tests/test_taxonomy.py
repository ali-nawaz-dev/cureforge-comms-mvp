from pathlib import Path

from packages.taxonomy import load_taxonomy

TAXONOMY_PATH = Path("data/taxonomy_v0_2.json")


def test_taxonomy_loads_all_client_entities() -> None:
    taxonomy = load_taxonomy(TAXONOMY_PATH)

    assert taxonomy.schema_version == "0.2"
    assert taxonomy.declared_total_entities == 57
    assert len(taxonomy.institutes) == 56


def test_taxonomy_ids_are_strings_and_sub_institutes_roll_up() -> None:
    taxonomy = load_taxonomy(TAXONOMY_PATH)

    aad = taxonomy.get("34-AaD")
    assert aad.institute_id == "34-AaD"
    assert aad.parent_institute_id == "34"
    assert taxonomy.parent_for_matching("34-AaD", rollup_sub_institutes=True) == "34"
    assert taxonomy.parent_for_matching("19", rollup_sub_institutes=True) == "17"


def test_verify_cicl_loads_with_null_names() -> None:
    taxonomy = load_taxonomy(TAXONOMY_PATH)

    institute = taxonomy.get("1")
    assert institute.name_status == "VERIFY_CICL"
    assert institute.long_name is None


def test_resolve_entries_suppress_outreach() -> None:
    taxonomy = load_taxonomy(TAXONOMY_PATH)

    assert taxonomy.get("4").name_status == "RESOLVE"
    assert taxonomy.is_resolve_pending("4") is True


def test_patent_anchor_is_independent_from_institute_id() -> None:
    taxonomy = load_taxonomy(TAXONOMY_PATH)

    assert taxonomy.get("55").patent_anchor == "P27"
    assert taxonomy.get("27").patent_anchor is None

