from scripts.verify_production_i18n_matrix_v2 import release_identity


def test_release_identity_records_backend_and_workflow_sha(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "workflow-commit")
    monkeypatch.setenv("BACKEND_RELEASE_SHA", "backend-commit")

    assert release_identity() == {
        "release_sha": "backend-commit",
        "backend_release_sha": "backend-commit",
        "workflow_sha": "workflow-commit",
    }


def test_release_identity_falls_back_to_workflow_sha(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "workflow-commit")
    monkeypatch.delenv("BACKEND_RELEASE_SHA", raising=False)

    assert release_identity() == {
        "release_sha": "workflow-commit",
        "backend_release_sha": "workflow-commit",
        "workflow_sha": "workflow-commit",
    }
