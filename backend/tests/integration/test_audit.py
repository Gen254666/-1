import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.audit.service import write_audit
from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AuditLog

pytestmark = pytest.mark.integration


async def test_write_audit_persists_entry(session: AsyncSession) -> None:
    user = User(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash="not-used",
        role=Role.USER,
    )
    session.add(user)
    await session.flush()

    entry = await write_audit(
        session,
        user_id=user.id,
        action="test.action",
        resource_type="thing",
        resource_id="42",
        detail={"value": 1},
        ip="127.0.0.1",
    )

    assert entry.id is not None

    stored = await session.scalar(select(AuditLog).where(AuditLog.id == entry.id))
    assert stored is not None
    assert stored.action == "test.action"
    assert stored.resource_type == "thing"
    assert stored.resource_id == "42"
    assert stored.detail == {"value": 1}
    assert stored.ip == "127.0.0.1"
