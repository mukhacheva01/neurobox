"""PaymentRepository."""
from sqlalchemy import select

from shared.db.models.payment import Payment
from shared.db.repositories.base import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    async def get_by_payment_id(self, payment_id: str) -> Payment | None:
        return await self.get_by("payment_id", payment_id)

    async def get_pending_for_user(self, user_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.user_id == user_id, Payment.status == "pending")
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
