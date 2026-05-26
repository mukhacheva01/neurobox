"""EventRepository."""
from shared.db.models.event import Event
from shared.db.repositories.base import BaseRepository


class EventRepository(BaseRepository[Event]):
    model = Event
