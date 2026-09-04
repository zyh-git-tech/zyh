#!/usr/bin/env python3
"""One-time migration from the local SQLite database to Render PostgreSQL.

The application never invokes this module during startup.  Run it explicitly
with SOURCE_SQLITE_URL and TARGET_DATABASE_URL (or the corresponding flags).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, delete, inspect, text
from sqlalchemy.orm import sessionmaker

# Allow execution as ``python scripts/...`` from the repository root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import (  # noqa: E402
    AgentRun,
    DiagnosisRecord,
    Equipment,
    LlmLabeledFeedback,
    MaintCase,
    PredictiveAnalysis,
    SopStep,
    SopTemplate,
    User,
    WorkOrder,
    WorkOrderStep,
    db,
)


SHARED_MODELS = (Equipment, SopTemplate, SopStep)
BUSINESS_MODELS = (
    DiagnosisRecord,
    WorkOrder,
    WorkOrderStep,
    PredictiveAnalysis,
    AgentRun,
    MaintCase,
    LlmLabeledFeedback,
)
ALL_MODELS = (User, *SHARED_MODELS, *BUSINESS_MODELS)
OWNERSHIP_TABLES = {model.__tablename__ for model in BUSINESS_MODELS if hasattr(model, "user_id")}


def normalize_url(url: str) -> str:
    """Make Render's legacy postgres:// URL SQLAlchemy-compatible."""
    value = (url or "").strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg2://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg2://" + value[len("postgresql://") :]
    return value


def model_columns(model) -> set[str]:
    return {column.name for column in model.__table__.columns}


def source_rows(source_conn, model) -> list[dict]:
    table = model.__tablename__
    available = {item["name"] for item in inspect(source_conn).get_columns(table)}
    columns = [name for name in model_columns(model) if name in available]
    if not columns:
        return []
    quoted_columns = ", ".join(f'"{name}"' for name in columns)
    primary_key = next(iter(model.__table__.primary_key.columns)).name
    statement = text(f'SELECT {quoted_columns} FROM "{table}" ORDER BY "{primary_key}"')
    return [dict(row) for row in source_conn.execute(statement).mappings()]


def clear_target(session) -> None:
    """Clear all migrated tables in FK-safe order for an explicit replacement."""
    for model in reversed(ALL_MODELS):
        session.execute(delete(model))
    session.commit()


def ensure_target_schema(target_engine) -> None:
    """Add ownership columns when the target was initialized by an older release."""
    if target_engine.dialect.name == "sqlite":
        return
    with target_engine.begin() as connection:
        inspector = inspect(connection)
        for table in OWNERSHIP_TABLES:
            columns = {item["name"] for item in inspector.get_columns(table)}
            if "user_id" not in columns:
                connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN user_id INTEGER'))
                connection.execute(text(f'CREATE INDEX IF NOT EXISTS "ix_{table}_user_id" ON "{table}" (user_id)'))


def sync_postgres_sequences(session) -> None:
    """Keep SERIAL/IDENTITY sequences ahead of explicitly preserved IDs."""
    if session.bind.dialect.name != "postgresql":
        return
    for model in ALL_MODELS:
        table = model.__tablename__
        pk = next(iter(model.__table__.primary_key.columns)).name
        session.execute(text(
            "SELECT setval(pg_get_serial_sequence(:table, :column), "
            "COALESCE((SELECT MAX(" + pk + ") FROM \"" + table + "\"), 1), true)"
        ), {"table": table, "column": pk})
    session.commit()


def target_is_nonempty(session) -> bool:
    return any(session.query(model).first() is not None for model in ALL_MODELS)


def copy_rows(session, source_conn, model, *, owner_id: int | None = None) -> int:
    rows = source_rows(source_conn, model)
    if not rows:
        return 0
    columns = model_columns(model)
    payload = []
    for row in rows:
        item = {key: value for key, value in row.items() if key in columns}
        for column in model.__table__.columns:
            if column.name in item and item[column.name] is not None:
                try:
                    python_type = column.type.python_type
                except (NotImplementedError, AttributeError):
                    python_type = None
                if python_type in {datetime, date} and isinstance(item[column.name], str):
                    item[column.name] = datetime.fromisoformat(item[column.name])
        if model in BUSINESS_MODELS and "user_id" in columns:
            item["user_id"] = owner_id
        payload.append(item)
    session.execute(model.__table__.insert(), payload)
    return len(payload)


def migrate(source_url: str, target_url: str, owner_username: str, *, replace: bool, dry_run: bool) -> OrderedDict:
    source_engine = create_engine(normalize_url(source_url), future=True)
    target_engine = create_engine(normalize_url(target_url), future=True)
    source_inspector = inspect(source_engine)
    missing = [model.__tablename__ for model in ALL_MODELS if not source_inspector.has_table(model.__tablename__)]
    if missing:
        raise RuntimeError(f"源数据库缺少表: {', '.join(missing)}")

    Session = sessionmaker(bind=target_engine, future=True)
    with Session() as session, source_engine.connect() as source_conn:
        db.metadata.create_all(target_engine)
        ensure_target_schema(target_engine)
        if target_is_nonempty(session):
            if not replace:
                raise RuntimeError("目标数据库已有数据；如需覆盖请显式添加 --replace。")
            clear_target(session)

        source_users = source_rows(source_conn, User)
        owner_source = next((row for row in source_users if row.get("username") == owner_username), None)
        if not owner_source:
            raise RuntimeError(f"源数据库中未找到归属账号 {owner_username!r}。")

        counts: OrderedDict[str, int] = OrderedDict()
        if dry_run:
            counts["users"] = len(source_users)
            for model in (*SHARED_MODELS, *BUSINESS_MODELS):
                counts[model.__tablename__] = len(source_rows(source_conn, model))
            counts["owner"] = owner_username
            return counts

        # Insert users first and map the source owner to the target owner ID.
        user_count = copy_rows(session, source_conn, User)
        session.flush()
        owner = session.query(User).filter_by(username=owner_username).one()
        counts["users"] = user_count

        for model in SHARED_MODELS:
            counts[model.__tablename__] = copy_rows(session, source_conn, model)
        for model in BUSINESS_MODELS:
            counts[model.__tablename__] = copy_rows(session, source_conn, model, owner_id=owner.id)
        session.commit()
        sync_postgres_sequences(session)
        counts["owner_id"] = owner.id
        return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=os.getenv("SOURCE_SQLITE_URL"), help="SQLite URL or file path")
    parser.add_argument("--target", default=os.getenv("TARGET_DATABASE_URL") or os.getenv("DATABASE_URL"), help="PostgreSQL URL")
    parser.add_argument("--owner", default=os.getenv("MIGRATION_OWNER", "zyh"), help="账号归属用户名")
    parser.add_argument("--replace", action="store_true", help="清空目标库后导入")
    parser.add_argument("--dry-run", action="store_true", help="只统计源数据，不写入目标库")
    args = parser.parse_args()
    if args.source and "://" not in args.source:
        args.source = f"sqlite:///{Path(args.source).resolve()}"
    if not args.source or not args.target:
        parser.error("请提供 --source/--target，或设置 SOURCE_SQLITE_URL/TARGET_DATABASE_URL。")
    if not args.dry_run and not normalize_url(args.target).startswith(("postgresql", "sqlite")):
        parser.error("目标数据库必须是 PostgreSQL URL（本地演练可使用 sqlite:/// URL）。")
    return args


if __name__ == "__main__":
    options = parse_args()
    result = migrate(options.source, options.target, options.owner, replace=options.replace, dry_run=options.dry_run)
    print("迁移统计:")
    for key, value in result.items():
        print(f"  {key}: {value}")
