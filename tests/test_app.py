# -*- coding: utf-8 -*-
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_VERSION", "test-version")

from app import app


def test_healthcheck_reports_application_and_database_status():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json == {"status": "ok", "version": "test-version", "database": "ok"}


def test_parameter_check_api_validates_json_input():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.post("/api/parameter-check", json={"rule_key": "spark_gap", "value": 0.8})

    assert response.status_code == 200
    assert response.json["result"]["status"] == "合格"


def test_parameter_check_api_returns_client_error_for_invalid_value():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.post("/api/parameter-check", json={"rule_key": "spark_gap", "value": "not-a-number"})

    assert response.status_code == 400
    assert response.json["status"] == "error"
