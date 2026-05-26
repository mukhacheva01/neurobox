"""AIRequestRepository."""
from shared.db.models.ai_request import AIRequest
from shared.db.repositories.base import BaseRepository


class AIRequestRepository(BaseRepository[AIRequest]):
    model = AIRequest
