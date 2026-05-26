"""Generic async repository."""
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id: Any) -> T | None:
        return await self.session.get(self.model, id)

    async def get_by(self, field: str, value: Any) -> T | None:
        col = getattr(self.model, field)
        result = await self.session.execute(select(self.model).where(col == value))
        return result.scalar_one_or_none()

    async def list(self, **filters: Any) -> Sequence[T]:
        q = select(self.model)
        for field, value in filters.items():
            q = q.where(getattr(self.model, field) == value)
        result = await self.session.execute(q)
        return result.scalars().all()

    async def create(self, **data: Any) -> T:
        obj = self.model(**data)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, id: Any, **data: Any) -> T | None:
        obj = await self.get(id)
        if obj is None:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        await self.session.flush()
        return obj

    async def delete(self, id: Any) -> bool:
        obj = await self.get(id)
        if obj is None:
            return False
        await self.session.delete(obj)
        await self.session.flush()
        return True
