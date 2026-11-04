import pytest_asyncio

from app.db.base import init_db, make_engine, make_session_factory


@pytest_asyncio.fixture
async def engine():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return make_session_factory(engine)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s
