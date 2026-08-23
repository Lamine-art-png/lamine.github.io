from __future__ import annotations


def test_assurance_source_ga_requires_real_production_build_identity(monkeypatch, db):
    from app.core.config import settings
    from app.services.assurance_rollout import assurance_access, configured_release_state

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ASSURANCE_RELEASE_STATE", "")
    monkeypatch.setattr(settings, "ASSURANCE_INTERNAL_ORGANIZATION_IDS", "")
    monkeypatch.setattr(settings, "ASSURANCE_CANARY_ORGANIZATION_IDS", "")
    for name in ("RENDER_GIT_COMMIT", "GIT_SHA", "COMMIT_SHA", "SOURCE_VERSION"):
        monkeypatch.delenv(name, raising=False)

    # A local process merely claiming to be production stays fail-closed.
    assert configured_release_state() == "disabled"
    assert assurance_access(db, None) == (False, "disabled", "general")

    # A real immutable production deployment inherits the founder-approved GA default.
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    assert configured_release_state() == "general"
    assert assurance_access(db, None) == (True, "general", "general")


def test_assurance_explicit_kill_switch_always_overrides_source_ga(monkeypatch, db):
    from app.core.config import settings
    from app.services.assurance_rollout import assurance_access, configured_release_state

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "b" * 40)
    monkeypatch.setattr(settings, "ASSURANCE_RELEASE_STATE", "disabled")

    assert configured_release_state() == "disabled"
    assert assurance_access(db, None) == (False, "disabled", "general")


def test_assurance_staging_and_invalid_override_remain_fail_closed(monkeypatch):
    from app.core.config import settings
    from app.services.assurance_rollout import configured_release_state

    monkeypatch.setattr(settings, "APP_ENV", "staging")
    monkeypatch.setattr(settings, "ASSURANCE_RELEASE_STATE", "")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "c" * 40)
    assert configured_release_state() == "disabled"

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ASSURANCE_RELEASE_STATE", "not-a-release-state")
    assert configured_release_state() == "disabled"
