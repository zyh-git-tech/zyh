# -*- coding: utf-8 -*-
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_VERSION", "test-version")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin")

from app import app


def login(client):
    return client.post("/login", data={"username": "admin", "password": "admin"})


def test_business_pages_require_login_but_healthcheck_is_public():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        assert client.get("/").status_code == 302
        assert "/login" in client.get("/agent").headers["Location"]
        assert client.get("/healthz").status_code == 200


def test_login_redirects_to_requested_page_and_logout_clears_session():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/agent")
        response = client.post("/login", data={"username": "admin", "password": "admin", "next": "/agent"})
        assert response.status_code == 302 and response.headers["Location"].endswith("/agent")
        assert client.get("/agent").status_code == 200
        client.post("/logout")
        assert client.get("/").status_code == 302


def test_invalid_login_does_not_authenticate():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert response.status_code == 200
        assert client.get("/").status_code == 302


def test_healthcheck_reports_application_and_database_status():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        login(client)
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "version": "test-version", "database": "ok"}


def test_parameter_check_api_validates_json_input():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        login(client)
        response = client.post("/api/parameter-check", json={"rule_key": "spark_gap", "value": 0.8})

    assert response.status_code == 200
    assert response.json["result"]["status"] == "合格"


def test_parameter_check_api_returns_client_error_for_invalid_value():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        login(client)
        response = client.post("/api/parameter-check", json={"rule_key": "spark_gap", "value": "not-a-number"})

    assert response.status_code == 400
    assert response.json["status"] == "error"


def test_capabilities_probe_is_non_sensitive():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        login(client)
        response = client.get("/api/capabilities")

    assert response.status_code == 200
    payload = response.json
    assert payload["retrieval"]["active"] in {"keyword", "chroma"}
    assert payload["vision"]["active"] in {"heuristic", "yolo"}
    assert payload["predictive"]["active"] == "deterministic"
    assert payload["llm"]["provider"] == "qwen"
    assert payload["llm"]["active"] in {"offline", "qwen"}
    assert "configured" in payload["llm"]
    assert "API_KEY" not in response.get_data(as_text=True)
