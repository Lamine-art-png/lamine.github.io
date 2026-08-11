from scripts.platform_api_stripe_provision import LIVE_CONFIRMATION, main


def test_stripe_provision_defaults_to_dry_run(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["platform_api_stripe_provision.py"])
    monkeypatch.delenv("PLATFORM_API_STRIPE_SECRET_KEY", raising=False)
    assert main() == 0
    assert '"dry_run": true' in capsys.readouterr().out


def test_stripe_provision_refuses_live_without_exact_confirmation(monkeypatch):
    monkeypatch.setattr("sys.argv", ["platform_api_stripe_provision.py", "--live", "--apply"])
    monkeypatch.setenv("PLATFORM_API_STRIPE_SECRET_KEY", "sk_live_not_real")
    assert main() == 2
    monkeypatch.setattr("sys.argv", ["platform_api_stripe_provision.py", "--live", "--apply", "--confirm-live", LIVE_CONFIRMATION])
