from uuid import uuid4

import pytest

from packages.common.schemas import EventEnvelope


@pytest.fixture
def sample_event_envelope() -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        topic="external_signal.telegram.13",
        payload={"source": "telegram"},
    )

