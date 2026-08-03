from app.services import field_live_rate_limit as limiter


def test_live_rate_limit_channels_are_isolated(monkeypatch):
    monkeypatch.setattr(limiter.settings, "REDIS_URL", "")
    limiter._MEMORY.clear()
    vision = [
        limiter.check_field_live_analysis_limit("org", "user", channel="vision")
        for _ in range(8)
    ]
    assert all(item.allowed for item in vision)
    assert not limiter.check_field_live_analysis_limit("org", "user", channel="vision").allowed

    speech = [
        limiter.check_field_live_analysis_limit("org", "user", channel="speech")
        for _ in range(6)
    ]
    assert all(item.allowed for item in speech)
    assert not limiter.check_field_live_analysis_limit("org", "user", channel="speech").allowed
