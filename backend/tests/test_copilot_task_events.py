from app.api.v1.copilot_tasks import parse_last_event_id


def test_parse_last_event_id_accepts_positive_integer():
    assert parse_last_event_id("12") == 12


def test_parse_last_event_id_rejects_invalid_values():
    assert parse_last_event_id("bad") == 0
    assert parse_last_event_id("-1") == 0
