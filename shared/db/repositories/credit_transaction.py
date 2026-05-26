"""CreditTransactionRepository."""
from shared.db.models.payment import CreditTransaction
from shared.db.repositories.base import BaseRepository


class CreditTransactionRepository(BaseRepository[CreditTransaction]):
    model = CreditTransaction
