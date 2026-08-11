"""Temporary: dump ORM metadata DDL via a mock engine (no DB needed)."""
from sqlalchemy import create_mock_engine

import qorder_api.models  # noqa: F401  (registers tables)
from qorder_api.db import Base

lines: list[str] = []


def _dump(sql, *args, **kwargs):
    lines.append(str(sql.compile(dialect=engine.dialect)).strip())


engine = create_mock_engine("postgresql+psycopg2://", _dump)
Base.metadata.create_all(engine, checkfirst=False)

text = "\n".join(lines)
# Show only the interesting constraint/index lines to keep output focused.
for needle in (
    "CREATE UNIQUE INDEX uq_one_open_session_per_table",
    "CHECK (prep_time_minutes",
    "CHECK (prep_time_snapshot",
    "CHECK (quantity",
    "ck_users_role_credentials",
    "uq_tables_qr_token",
    "uq_tables_restaurant_number",
    "uq_users_restaurant_email",
    "ix_order_items_restaurant_status",
    "ix_table_sessions_status_activity",
):
    hit = [ln for ln in text.splitlines() if needle in ln]
    print(f"[{'OK ' if hit else 'MISSING'}] {needle}")

print("TABLES_EMITTED", text.count("CREATE TABLE"))
