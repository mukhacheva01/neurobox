"""UserRepository."""

from shared.db.models.user import User
from shared.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_referral_code(self, code: str) -> User | None:
        return await self.get_by("referral_code", code)

    async def get_or_create(self, user_id: int, username: str | None = None, first_name: str | None = None) -> tuple[User, bool]:
        user = await self.get(user_id)
        if user is not None:
            return user, False
        import secrets as _secrets
        user = await self.create(
            id=user_id,
            username=username,
            first_name=first_name,
            referral_code=_secrets.token_urlsafe(8),
        )
        return user, True
