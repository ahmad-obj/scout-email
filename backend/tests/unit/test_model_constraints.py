import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from scout_email.db.session import create_engine_and_sessionmaker


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_are_enforced(tmp_path):
    engine, session_factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}"
    )
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE parent(id INTEGER PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"))

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(text("INSERT INTO child(id, parent_id) VALUES (1, 999)"))
            await session.commit()
        await session.rollback()

    await engine.dispose()
