import json


def test_evaluation_sample_report_has_corporate_language(client):
    response = client.get("/evaluation/sample-report")

    assert response.status_code == 200
    assert "AGRO-AI Sample Report" in response.text
    assert "evaluation workflows" in response.text
    assert "demo" not in response.text.lower()


def test_legacy_sample_report_keeps_route_without_visible_demo_language(client):
    response = client.get("/demo/sample-report")

    assert response.status_code == 200
    assert "AGRO-AI Sample Report" in response.text
    assert "demo" not in response.text.lower()


def test_evaluation_run_points_to_evaluation_report_endpoint(client):
    response = client.post("/v1/evaluation/run", json={"block_ids": ["B1"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_endpoint"] == "/v1/evaluation/report"
    assert "evaluation logic" in payload["prescriptions"][0]["reason"]
    assert "demo" not in json.dumps(payload).lower()


def test_legacy_run_response_uses_evaluation_language(client):
    response = client.post("/v1/demo/run", json={"block_ids": ["B1"]})

    assert response.status_code == 200
    assert "demo" not in json.dumps(response.json()).lower()


def test_openapi_documents_evaluation_routes_not_legacy_demo_routes(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/evaluation/recommendation" in paths
    assert "/v1/evaluation/blocks" in paths
    assert "/v1/evaluation/run" in paths
    assert "/v1/evaluation/report" in paths
    assert "/v1/demo/recommendation" not in paths
    assert "/v1/demo/blocks" not in paths
    assert "/v1/demo/run" not in paths
    assert "/v1/demo/report" not in paths
