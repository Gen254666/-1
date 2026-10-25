import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.models.market import PricePoint
from steel_core.db.seed import seed_all

pytestmark = pytest.mark.integration


async def test_seed_creates_no_public_points(session: AsyncSession) -> None:
    result = await seed_all(session, admin_username="admin", admin_password="ChangeMe123!")

    assert result["points"] == 0
    assert int(await session.scalar(select(func.count()).select_from(PricePoint)) or 0) == 0
