import json
import string
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.auth import get_current_user, get_current_user_optional
from app.config import settings
from app.database import get_db
from app.models import Link, User
from app.redis_client import get_redis
from app.schemas import LinkCreate, LinkUpdate, LinkResponse, LinkStats, ExpiredLinkInfo

router = APIRouter(tags=["links"])

ALPHABET = string.ascii_letters + string.digits


def generate_short_code(length: int = 6) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


# ---------- helpers ----------

def _cache_key(short_code: str) -> str:
    return f"link:{short_code}"


def _search_cache_key(url: str) -> str:
    return f"search:{url}"


async def _invalidate_cache(rc: aioredis.Redis, short_code: str, original_url: str | None = None):
    await rc.delete(_cache_key(short_code))
    await rc.delete(f"stats:{short_code}")
    if original_url:
        await rc.delete(_search_cache_key(original_url))


async def _get_active_link(db: AsyncSession, short_code: str) -> Link:
    result = await db.execute(select(Link).where(Link.short_code == short_code))
    link = result.scalar_one_or_none()
    if not link or link.is_expired:
        raise HTTPException(status_code=404, detail="Short link not found")
    if link.expires_at and link.expires_at <= datetime.now(timezone.utc):
        link.is_expired = True
        await db.commit()
        raise HTTPException(status_code=410, detail="Short link has expired")
    return link


# ---------- Create ----------

@router.post("/links/shorten", response_model=LinkResponse, status_code=status.HTTP_201_CREATED)
async def create_short_link(
    data: LinkCreate,
    db: AsyncSession = Depends(get_db),
    rc: aioredis.Redis = Depends(get_redis),
    user: User | None = Depends(get_current_user_optional),
):
    original = str(data.original_url)

    if data.custom_alias:
        exists = await db.execute(select(Link).where(Link.short_code == data.custom_alias))
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Alias already in use")
        short_code = data.custom_alias
    else:
        for _ in range(10):
            short_code = generate_short_code()
            exists = await db.execute(select(Link).where(Link.short_code == short_code))
            if not exists.scalar_one_or_none():
                break
        else:
            raise HTTPException(status_code=500, detail="Could not generate unique code")

    link = Link(
        short_code=short_code,
        original_url=original,
        expires_at=data.expires_at,
        owner_id=user.id if user else None,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    await rc.setex(
        _cache_key(short_code),
        settings.cache_ttl,
        json.dumps({"original_url": link.original_url, "id": link.id}),
    )

    return link


# ---------- Search (BEFORE {short_code} routes!) ----------

@router.get("/links/search", response_model=list[LinkResponse])
async def search_links(
    original_url: str = Query(...),
    db: AsyncSession = Depends(get_db),
    rc: aioredis.Redis = Depends(get_redis),
):
    cache_key = _search_cache_key(original_url)
    cached = await rc.get(cache_key)
    if cached:
        return [LinkResponse(**item) for item in json.loads(cached)]

    result = await db.execute(
        select(Link).where(Link.original_url == original_url, Link.is_expired == False)
    )
    links = result.scalars().all()
    if not links:
        raise HTTPException(status_code=404, detail="No links found for this URL")

    response = [
        LinkResponse(
            short_code=lnk.short_code,
            original_url=lnk.original_url,
            created_at=lnk.created_at,
            expires_at=lnk.expires_at,
        )
        for lnk in links
    ]
    await rc.setex(
        cache_key,
        settings.cache_ttl,
        json.dumps([item.model_dump(mode="json") for item in response]),
    )
    return response


# ---------- Expired links history (BEFORE {short_code} routes!) ----------

@router.get("/links/expired/history", response_model=list[ExpiredLinkInfo])
async def expired_links_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Link).where(Link.is_expired == True, Link.owner_id == user.id)
    )
    return result.scalars().all()


# ---------- Redirect ----------

@router.get("/links/{short_code}", response_class=RedirectResponse)
async def redirect_link(
    short_code: str,
    db: AsyncSession = Depends(get_db),
    rc: aioredis.Redis = Depends(get_redis),
):
    cached = await rc.get(_cache_key(short_code))
    if cached:
        data = json.loads(cached)
        now = datetime.now(timezone.utc)
        await db.execute(
            update(Link)
            .where(Link.short_code == short_code, Link.is_expired == False)
            .values(click_count=Link.click_count + 1, last_used_at=now)
        )
        await db.commit()
        return RedirectResponse(url=data["original_url"], status_code=307)

    link = await _get_active_link(db, short_code)
    link.click_count += 1
    link.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    await rc.setex(
        _cache_key(short_code),
        settings.cache_ttl,
        json.dumps({"original_url": link.original_url, "id": link.id}),
    )

    return RedirectResponse(url=link.original_url, status_code=307)


# ---------- Stats ----------

@router.get("/links/{short_code}/stats", response_model=LinkStats)
async def link_stats(
    short_code: str,
    db: AsyncSession = Depends(get_db),
    rc: aioredis.Redis = Depends(get_redis),
):
    stats_key = f"stats:{short_code}"
    cached = await rc.get(stats_key)
    if cached:
        return LinkStats(**json.loads(cached))

    link = await _get_active_link(db, short_code)
    stats = LinkStats(
        short_code=link.short_code,
        original_url=link.original_url,
        created_at=link.created_at,
        last_used_at=link.last_used_at,
        click_count=link.click_count,
        expires_at=link.expires_at,
    )
    await rc.setex(stats_key, settings.cache_ttl, stats.model_dump_json())
    return stats


# ---------- Delete ----------

@router.delete("/links/{short_code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(
    short_code: str,
    db: AsyncSession = Depends(get_db),
    rc: aioredis.Redis = Depends(get_redis),
    user: User = Depends(get_current_user),
):
    link = await _get_active_link(db, short_code)
    if link.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not your link")
    await _invalidate_cache(rc, short_code, link.original_url)
    await db.delete(link)
    await db.commit()


# ---------- Update ----------

@router.put("/links/{short_code}", response_model=LinkResponse)
async def update_link(
    short_code: str,
    data: LinkUpdate,
    db: AsyncSession = Depends(get_db),
    rc: aioredis.Redis = Depends(get_redis),
    user: User = Depends(get_current_user),
):
    link = await _get_active_link(db, short_code)
    if link.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not your link")
    old_url = link.original_url
    link.original_url = str(data.original_url)
    await db.commit()
    await db.refresh(link)
    await _invalidate_cache(rc, short_code, old_url)
    await rc.setex(
        _cache_key(short_code),
        settings.cache_ttl,
        json.dumps({"original_url": link.original_url, "id": link.id}),
    )
    return link
