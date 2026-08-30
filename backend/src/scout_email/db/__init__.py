"""Database models, sessions, and repositories."""

from scout_email.db.llm_models import LLMGeneration
from scout_email.db import models as _models

# Keep the historical ``scout_email.db.models`` import surface stable while
# allowing generation metadata to live in its own focused module.
_models.LLMGeneration = LLMGeneration

__all__ = ["LLMGeneration"]
