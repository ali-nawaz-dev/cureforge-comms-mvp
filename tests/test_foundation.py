from apps.dashboard.app import dashboard_views
from packages.bus import InMemoryBus
from packages.common.hashing import canonical_json, normalized_content_hash
from packages.common.schemas import EventEnvelope


def test_canonical_json_is_stable() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_normalized_content_hash_deduplicates_whitespace_and_case() -> None:
    assert normalized_content_hash("  Hello   World ") == normalized_content_hash("hello world")


def test_in_memory_bus_supports_wildcard_subscription(sample_event_envelope: EventEnvelope) -> None:
    bus = InMemoryBus()
    seen: list[EventEnvelope] = []
    bus.subscribe("external_signal.*", seen.append)

    bus.publish(sample_event_envelope)

    assert seen == [sample_event_envelope]


def test_dashboard_declares_required_views() -> None:
    assert "approval_queue" in dashboard_views()
    assert "suppression_reasons" in dashboard_views()

