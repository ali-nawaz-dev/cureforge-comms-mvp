from apps.dashboard.app import _bool_field, _contact_from_row, _list_field


def test_dashboard_contact_upload_helpers_parse_csv_style_values() -> None:
    contact = _contact_from_row(
        {
            "contact_type": "INVESTOR",
            "name": "Client Contact",
            "organization": "Client Org",
            "focus_areas": "3, 34-AaD",
            "stated_thesis_tags": "longevity; payor",
            "warm_signal_score": "75",
            "under_nda": "yes",
            "source_provenance": "CLIENT_UPLOAD",
        }
    )

    assert contact.focus_areas == ["3", "34-AaD"]
    assert contact.stated_thesis_tags == ["longevity", "payor"]
    assert contact.under_nda is True
    assert contact.source_provenance == {"seed_source": "CLIENT_UPLOAD"}


def test_dashboard_list_and_bool_helpers() -> None:
    assert _list_field("a; b, c") == ["a", "b", "c"]
    assert _bool_field("true") is True
    assert _bool_field("no") is False

