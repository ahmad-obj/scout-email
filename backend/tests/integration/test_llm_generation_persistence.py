from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from scout_email.db.base import Base
from scout_email.db.models import LLMGeneration
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.persistence import LLMGenerationRecorder
from scout_email.llm.schemas import GenerationMetadata


@pytest.mark.asyncio
async def test_generation_recorder_persists_provider_model_prompt_and_status(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'llm.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        recorder = LLMGenerationRecorder(session)
        metadata = GenerationMetadata(
            task="researcher",
            provider="fake",
            model="fake-1",
            prompt_version="researcher:v1",
            status="COMPLETE",
            repair_attempted=False,
            generated_at=datetime.now(UTC),
        )
        row_id = await recorder.record(metadata)

        assert row_id > 0
        assert await session.scalar(select(func.count()).select_from(LLMGeneration)) == 1
        row = await session.get(LLMGeneration, row_id)
        assert row is not None
        assert row.task == "researcher"
        assert row.provider == "fake"
        assert row.model == "fake-1"
        assert row.prompt_version == "researcher:v1"
        assert row.status == "COMPLETE"
        assert row.repair_attempted is False
        assert row.generated_at is not None

    await engine.dispose()
