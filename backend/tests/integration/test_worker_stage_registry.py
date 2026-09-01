from importlib import import_module

import pytest

from scout_email.db.base import Base
from scout_email.db.session import create_engine_and_sessionmaker


EXPECTED_JOB_KINDS = {
    "MAPS_SCOUT_SEARCH",
    "ENRICH",
    "CRAWL_EVIDENCE",
    "RESEARCH",
    "STRATEGY",
    "WRITER_CRITIC",
}


@pytest.mark.asyncio
async def test_worker_registers_every_n8n_stage_handler(tmp_path):
    runtime = import_module("scout_email.jobs.runtime")
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'stage-registry.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        handlers = runtime.build_handlers(
            session,
            browser=object(),
            gateway=object(),
            playbook=object(),
            data_root=tmp_path,
        )
        assert set(handlers) == EXPECTED_JOB_KINDS

    await engine.dispose()
