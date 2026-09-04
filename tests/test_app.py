# -*- coding: utf-8 -*-
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_VERSION", "test-version")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin")

from app import app
from models import db, DiagnosisRecord, User, WorkOrder


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


def test_register_login_switch_account_and_logout():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        assert client.get("/register").status_code == 200
        response = client.post("/register", data={"username": "operator_1", "password": "password123", "confirm_password": "password123"})
        assert response.status_code == 302
        duplicate = client.post("/register", data={"username": "operator_1", "password": "password123", "confirm_password": "password123"})
        assert duplicate.status_code == 200
        assert "已存在" in duplicate.get_data(as_text=True)
        assert client.post("/login", data={"username": "operator_1", "password": "password123"}).status_code == 302
        assert client.post("/switch-account").status_code == 302
        assert client.get("/").status_code == 302


def test_registration_requires_matching_confirmation_and_hides_workspace_navigation():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get("/register").get_data(as_text=True)
        assert 'name="confirm_password"' in page
        assert 'class="sidebar"' not in page
        response = client.post("/register", data={
            "username": "confirmation_user", "password": "password123", "confirm_password": "different123",
        })
        assert response.status_code == 200
        assert "两次输入的密码不一致" in response.get_data(as_text=True)


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


def test_business_records_are_isolated_between_users_and_visible_to_admin():
    app.config.update(TESTING=True)
    user_a = f"isolation_a_{uuid.uuid4().hex[:8]}"
    user_b = f"isolation_b_{uuid.uuid4().hex[:8]}"
    client_a = app.test_client()
    client_b = app.test_client()
    admin_client = app.test_client()
    client_a.post("/register", data={"username": user_a, "password": "password123", "confirm_password": "password123"})
    client_b.post("/register", data={"username": user_b, "password": "password123", "confirm_password": "password123"})
    client_a.post("/login", data={"username": user_a, "password": "password123"})
    client_b.post("/login", data={"username": user_b, "password": "password123"})

    with app.app_context():
        owner = User.query.filter_by(username=user_a).one()
        diagnosis = DiagnosisRecord(
            user_id=owner.id, trace_id="DX-ISOLATION-A", device_model="ZONTES-250",
            query_text="仅用于账号隔离测试", risk_level="低风险", confidence=0.9,
            answer="测试诊断结果",
        )
        db.session.add(diagnosis)
        db.session.flush()
        order = WorkOrder(
            user_id=owner.id, order_no="WO-ISOLATION-A", diagnosis_id=diagnosis.id,
            title=f"仅属于 {user_a} 的工单", device_model="ZONTES-250",
            priority="P3", assignee="测试", status="待处理",
        )
        db.session.add(order)
        db.session.commit()
        order_id = order.id

    order_title = f"仅属于 {user_a} 的工单"
    assert order_title in client_a.get("/work-orders").get_data(as_text=True)
    assert order_title not in client_b.get("/work-orders").get_data(as_text=True)
    assert client_b.get(f"/work-orders/{order_id}").status_code == 404

    admin_client.post("/login", data={"username": "admin", "password": "admin"})
    assert order_title in admin_client.get("/work-orders").get_data(as_text=True)
