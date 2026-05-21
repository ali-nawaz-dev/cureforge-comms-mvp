"""Phase 6: taxonomy + reviewer schema validators."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.hitl.reviewers import ReviewerSchemaError, load_reviewers
from packages.taxonomy.loader import TaxonomySchemaError, load_taxonomy


def test_taxonomy_loader_rejects_unknown_id_type(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"id_type": "integer", "schema_version": "0.2", "tiers": []}))
    with pytest.raises(TaxonomySchemaError):
        load_taxonomy(path)


def test_taxonomy_loader_rejects_dangling_parent(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(
            {
                "id_type": "string",
                "schema_version": "0.2",
                "federation_count": {"total_entities": 1},
                "tiers": [
                    {
                        "tier_id": 1,
                        "tier_name": "Tier A",
                        "institutes": [
                            {
                                "institute_id": "1",
                                "name_status": "CONFIRMED",
                                "is_sub_institute": True,
                                "parent_institute_id": "999",
                            }
                        ],
                    }
                ],
            }
        )
    )
    with pytest.raises(TaxonomySchemaError):
        load_taxonomy(path)


def test_taxonomy_loader_rejects_duplicate_institute_id(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps(
            {
                "id_type": "string",
                "schema_version": "0.2",
                "federation_count": {"total_entities": 2},
                "tiers": [
                    {
                        "tier_id": 1,
                        "tier_name": "Tier A",
                        "institutes": [
                            {"institute_id": "1", "name_status": "CONFIRMED"},
                            {"institute_id": "1", "name_status": "CONFIRMED"},
                        ],
                    }
                ],
            }
        )
    )
    with pytest.raises(TaxonomySchemaError):
        load_taxonomy(path)


def test_reviewers_strict_mode_rejects_unknown_role(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(json.dumps([{"email": "x@example.com", "role": "made_up_role"}]))
    with pytest.raises(ReviewerSchemaError):
        load_reviewers(str(path), strict=True)


def test_reviewers_lax_mode_skips_bad_rows(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps(
            [
                {"email": "ok@example.com", "role": "principal_investigator"},
                {"email": "no-at-sign", "role": "principal_investigator"},
                {"role": "principal_investigator"},  # missing email
            ]
        )
    )
    loaded = load_reviewers(str(path))
    assert [r.email for r in loaded] == ["ok@example.com"]
