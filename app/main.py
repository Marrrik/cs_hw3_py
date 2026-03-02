import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from sqlalchemy import update, delete

from app.config import settings
from app.database import engine, Base, async_session
from app.models import Link
from app.routers import auth_router, links_router


async def cleanup_expired_links():
    """Background task: mark expired links and optionally delete unused ones."""
    while True:
        await asyncio.sleep(60)  # check every minute
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            # Mark links past their expires_at
            await db.execute(
                update(Link)
                .where(Link.expires_at <= now, Link.is_expired == False)
                .values(is_expired=True)
            )
            # Delete links unused for N days (if configured)
            if settings.unused_links_days > 0:
                cutoff = now - timedelta(days=settings.unused_links_days)
                await db.execute(
                    delete(Link).where(
                        Link.is_expired == False,
                        Link.last_used_at != None,
                        Link.last_used_at < cutoff,
                    )
                )
            await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    task = asyncio.create_task(cleanup_expired_links())
    yield
    task.cancel()
    await engine.dispose()


app = FastAPI(title="Link Shortener", version="1.0.0", lifespan=lifespan)

app.include_router(auth_router.router)
app.include_router(links_router.router)


@app.get("/", tags=["health"])
async def health():
    return {"status": "ok"}
