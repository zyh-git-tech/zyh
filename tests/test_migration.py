import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import DiagnosisRecord, Equipment, User, WorkOrder, db
from scripts.migrate_sqlite_to_postgres import migrate


def build_source(path):
    engine = create_engine(f"sqlite:///{path}")
    db.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        admin = User(username="admin", password_hash="hash", role="admin")
        owner = User(username="zyh", password_hash="hash", role="user")
        session.add_all([admin, owner, Equipment(name="测试设备", model="TEST-01")])
        session.flush()
        diagnosis = DiagnosisRecord(
            trace_id="DX-MIGRATION-TEST", query_text="迁移测试", risk_level="低风险", confidence=0.8,
            answer="迁移测试诊断结果",
        )
        session.add(diagnosis)
        session.flush()
        session.add(WorkOrder(
            order_no="WO-MIGRATION-TEST", diagnosis_id=diagnosis.id,
            title="迁移测试工单", device_model="TEST-01", priority="P3", assignee="测试",
        ))
        session.commit()


def test_migration_preserves_counts_and_assigns_zyh(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    build_source(source)

    counts = migrate(f"sqlite:///{source}", f"sqlite:///{target}", "zyh", replace=False, dry_run=False)

    assert counts["work_orders"] == 1
    assert counts["diagnosis_records"] == 1
    with sqlite3.connect(target) as connection:
        owner_id = connection.execute("SELECT id FROM users WHERE username='zyh'").fetchone()[0]
        assert connection.execute("SELECT COUNT(*) FROM work_orders WHERE user_id=?", (owner_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM equipments").fetchone()[0] == 1


def test_migration_requires_explicit_replace_for_nonempty_target(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    build_source(source)
    build_source(target)

    with pytest.raises(RuntimeError, match="--replace"):
        migrate(f"sqlite:///{source}", f"sqlite:///{target}", "zyh", replace=False, dry_run=False)
