import datetime as _dt

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from httpx import AsyncClient, ASGITransport

from app.database import Base, get_db
from app.redis_client import get_redis
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


# SQLite returns naive datetimes; the app expects timezone-aware ones.
# This listener patches loaded instances so comparisons work correctly.
@event.listens_for(Base, "load", propagate=True)
def _ensure_tz_aware(target, _context):
    for col in target.__table__.columns:
        if hasattr(col.type, "timezone") and col.type.timezone:
            val = getattr(target, col.name, None)
            if isinstance(val, _dt.datetime) and val.tzinfo is None:
                set_committed_value(
                    target, col.name, val.replace(tzinfo=_dt.timezone.utc)
                )


class FakeRedis:
    """In-memory Redis mock for tests."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value

    async def delete(self, *keys: str):
        for k in keys:
            self._store.pop(k, None)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value

    def clear(self):
        self._store.clear()


fake_redis = FakeRedis()


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


async def override_get_redis():
    return fake_redis


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_redis] = override_get_redis


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    fake_redis.clear()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture
def redis_store():
    return fake_redis


@pytest_asyncio.fixture
async def auth_token(client: AsyncClient):
    await client.post(
        "/auth/register", json={"username": "testuser", "password": "testpass123"}
    )
    resp = await client.post(
        "/auth/login", data={"username": "testuser", "password": "testpass123"},
    )
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def auth_headers(auth_token: str):
    return {"Authorization": f"Bearer {auth_token}"}
