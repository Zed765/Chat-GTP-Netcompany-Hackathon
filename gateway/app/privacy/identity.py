"""Who is behind one event: an admin may look it up."""

from fastapi import HTTPException, status

from gateway.app.db.session import Database
from gateway.app.events.models import Event
from gateway.app.privacy.directory import Directory
from gateway.app.privacy.schemas import IdentityOut


class Identities:
    def __init__(self, db: Database, directory: Directory) -> None:
        self._db = db
        self._directory = directory

    async def reveal(self, event_id: int) -> IdentityOut:
        async with self._db.session() as session:
            event = await session.get(Event, event_id)
        if event is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such event")
        person = self._directory.find_by_pseudonym(event.user_pseudonym)
        if person is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "The person is no longer in the directory"
            )
        return IdentityOut(
            event_id=event_id,
            user_id=person.user_id,
            display_name=person.display_name,
            team=person.team,
        )
