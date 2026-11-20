from gateway.app.core.types import Principal
from gateway.app.events.writer import pseudonym

USER_PREFIX_CHARS = 16


def vault_conversation(principal: Principal, conversation_id: str, pseudonym_key: bytes) -> str:
    """The vault's name for a caller's conversation. It is tied to the user, so knowing
    someone else's conversation ID gives no way into their vault."""
    return f"{pseudonym(principal.user_id, pseudonym_key)[:USER_PREFIX_CHARS]}:{conversation_id}"
