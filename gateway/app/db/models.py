"""Imports every model so `Base.metadata` is complete for migrations and tests."""

from gateway.app.db.base import Base
from gateway.app.discovery import models as discovery_models
from gateway.app.events import models as events_models
from gateway.app.policy import models as policy_models
from gateway.app.privacy import models as privacy_models
from gateway.app.protected import models as protected_models

__all__ = [
    "Base",
    "discovery_models",
    "events_models",
    "policy_models",
    "privacy_models",
    "protected_models",
]
