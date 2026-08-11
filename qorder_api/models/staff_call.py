"""``staff_calls`` — the single "call staff" button flow (R7).

Kept minimal on purpose: no ``type`` classification in the MVP. Every call is
tied to a session (the button only appears after a QR scan opened one — R2.4).
Cooldown is enforced per table in the service layer using ``created_at``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from qorder_api.db import Base
from qorder_api.models._columns import (
    created_at_column,
    ts_column,
    uuid_fk,
    uuid_pk,
)
from qorder_api.models.enums import StaffCallStatus, staff_call_status_enum


class StaffCall(Base):
    """A request to call a staff member to a table."""

    __tablename__ = "staff_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    table_id: Mapped[uuid.UUID] = uuid_fk("tables.id", ondelete="CASCADE")
    table_session_id: Mapped[uuid.UUID] = uuid_fk(
        "table_sessions.id", ondelete="CASCADE"
    )
    status: Mapped[StaffCallStatus] = mapped_column(
        staff_call_status_enum,
        nullable=False,
        server_default=StaffCallStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = created_at_column()
    acknowledged_at: Mapped[datetime | None] = ts_column(nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL"
    )
