from attendance_relay.settings import Settings
from attendance_relay.worker import _compute_backoff_seconds


def test_backoff_grows_and_capped() -> None:
    settings = Settings(
        backoff_base_seconds=2.0,
        backoff_max_seconds=5.0,
        backoff_jitter_seconds=0.0,
        outbound_api_key="test-key",
    )
    d1 = _compute_backoff_seconds(settings, 1)
    d2 = _compute_backoff_seconds(settings, 2)
    d3 = _compute_backoff_seconds(settings, 3)
    assert d1 == 2.0
    assert d2 == 4.0
    assert d3 == 5.0
