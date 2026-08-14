from scripts.verify_production_i18n_matrix_v2 import valid


def _payload(*, provider: str = "edge_catalog_cache", models=None):
    return {
        "status": "ok",
        "locale": "ar",
        "key_count": 4,
        "changed_count": 4,
        "catalog_sha256": "a" * 64,
        "providers": [provider],
        "models": [] if models is None else models,
    }


def test_provider_backed_translation_does_not_require_model_attribution():
    assert valid("ar", _payload())
    assert valid("ar", _payload(provider="public_translation_provider_chain_v4"))


def test_model_backed_translation_remains_valid():
    assert valid("ar", _payload(provider="cloudflare_workers_ai", models=["@cf/meta/llama-3.1-8b-instruct"]))


def test_missing_provider_attribution_is_rejected():
    payload = _payload()
    payload["providers"] = []
    assert not valid("ar", payload)
