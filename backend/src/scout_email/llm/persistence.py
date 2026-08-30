from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.db.models import LLMGeneration
from scout_email.llm.schemas import GenerationMetadata


class LLMGenerationRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, metadata: GenerationMetadata) -> int:
        row = LLMGeneration(
            task=metadata.task,
            provider=metadata.provider,
            model=metadata.model,
            prompt_version=metadata.prompt_version,
            status=metadata.status,
            repair_attempted=metadata.repair_attempted,
            generated_at=metadata.generated_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row.id
