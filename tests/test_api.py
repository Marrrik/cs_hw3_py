"""Functional API tests — all CRUD operations, auth, redirect, edge cases."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth import create_access_token
from app.models import Link


# ====================== Auth ======================


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        resp = await client.post(
            "/auth/register", json={"username": "newuser", "password": "pass123"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert "id" in data
        assert "created_at" in data

    async def test_register_duplicate(self, client: AsyncClient):
        await client.post(
            "/auth/register", json={"username": "dup", "password": "pass"}
        )
        resp = await client.post(
            "/auth/register", json={"username": "dup", "password": "pass"}
        )
        assert resp.status_code == 400
        assert "already taken" in resp.json()["detail"]


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        await client.post(
            "/auth/register", json={"username": "loginuser", "password": "pass123"}
        )
        resp = await client.post(
            "/auth/login", data={"username": "loginuser", "password": "pass123"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient):
        await client.post(
            "/auth/register", json={"username": "u1", "password": "right"}
        )
        resp = await client.post(
            "/auth/login", data={"username": "u1", "password": "wrong"}
        )
        assert resp.status_code == 401

    async def test_login_nonexistent(self, client: AsyncClient):
        resp = await client.post(
            "/auth/login", data={"username": "ghost", "password": "x"}
        )
        assert resp.status_code == 401


# ====================== Create link ======================


class TestCreateLink:
    async def test_create_anonymous(self, client: AsyncClient):
        resp = await client.post(
            "/links/shorten", json={"original_url": "https://example.com"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "short_code" in data
        assert "example.com" in data["original_url"]

    async def test_create_authenticated(self, client: AsyncClient, auth_headers):
        resp = await client.post(
            "/links/shorten",
            json={"original_url": "https://example.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

    async def test_custom_alias(self, client: AsyncClient):
        resp = await client.post(
            "/links/shorten",
            json={"original_url": "https://example.com", "custom_alias": "myalias"},
        )
        assert resp.status_code == 201
        assert resp.json()["short_code"] == "myalias"

    async def test_duplicate_alias(self, client: AsyncClient):
        await client.post(
            "/links/shorten",
            json={"original_url": "https://a.com", "custom_alias": "taken"},
        )
        resp = await client.post(
            "/links/shorten",
            json={"original_url": "https://b.com", "custom_alias": "taken"},
        )
        assert resp.status_code == 409

    async def test_with_expiry(self, client: AsyncClient):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        resp = await client.post(
            "/links/shorten",
            json={"original_url": "https://example.com", "expires_at": future},
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is not None

    async def test_invalid_url(self, client: AsyncClient):
        resp = await client.post(
            "/links/shorten", json={"original_url": "not-a-url"}
        )
        assert resp.status_code == 422

    async def test_code_collision_exhaustion(self, client: AsyncClient):
        await client.post(
            "/links/shorten",
            json={"original_url": "https://a.com", "custom_alias": "fixed"},
        )
        with patch(
            "app.routers.links_router.generate_short_code", return_value="fixed"
        ):
            resp = await client.post(
                "/links/shorten", json={"original_url": "https://b.com"}
            )
            assert resp.status_code == 500


# ====================== Redirect ======================


class TestRedirect:
    async def test_redirect(self, client: AsyncClient):
        create = await client.post(
            "/links/shorten", json={"original_url": "https://example.com"}
        )
        code = create.json()["short_code"]
        resp = await client.get(f"/links/{code}", follow_redirects=False)
        assert resp.status_code == 307
        assert "example.com" in resp.headers["location"]

    async def test_redirect_not_found(self, client: AsyncClient):
        resp = await client.get("/links/nope", follow_redirects=False)
        assert resp.status_code == 404

    async def test_redirect_no_cache(self, client: AsyncClient, redis_store):
        """Redirect through DB path (cache miss)."""
        create = await client.post(
            "/links/shorten", json={"original_url": "https://nocache.com"}
        )
        code = create.json()["short_code"]
        redis_store.clear()
        resp = await client.get(f"/links/{code}", follow_redirects=False)
        assert resp.status_code == 307

    async def test_redirect_increments_click(self, client: AsyncClient):
        create = await client.post(
            "/links/shorten", json={"original_url": "https://clicks.com"}
        )
        code = create.json()["short_code"]
        await client.get(f"/links/{code}", follow_redirects=False)
        await client.get(f"/links/{code}", follow_redirects=False)
        stats = await client.get(f"/links/{code}/stats")
        assert stats.json()["click_count"] >= 2

    async def test_redirect_expired(self, client: AsyncClient, redis_store):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        create = await client.post(
            "/links/shorten",
            json={"original_url": "https://exp.com", "expires_at": past},
        )
        code = create.json()["short_code"]
        redis_store.clear()
        resp = await client.get(f"/links/{code}", follow_redirects=False)
        assert resp.status_code == 410

    async def test_redirect_already_marked_expired(self, client: AsyncClient, redis_store):
        """Second access to expired link returns 404 (is_expired=True in DB)."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        create = await client.post(
            "/links/shorten",
            json={"original_url": "https://exp2.com", "expires_at": past},
        )
        code = create.json()["short_code"]
        redis_store.clear()
        await client.get(f"/links/{code}", follow_redirects=False)  # marks expired
        redis_store.clear()
        resp = await client.get(f"/links/{code}", follow_redirects=False)
        assert resp.status_code == 404


# ====================== Stats ======================


class TestStats:
    async def test_stats(self, client: AsyncClient):
        create = await client.post(
            "/links/shorten", json={"original_url": "https://stats.com"}
        )
        code = create.json()["short_code"]
        resp = await client.get(f"/links/{code}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["short_code"] == code
        assert data["click_count"] == 0

    async def test_stats_not_found(self, client: AsyncClient):
        resp = await client.get("/links/nope/stats")
        assert resp.status_code == 404

    async def test_stats_uses_cache(self, client: AsyncClient):
        create = await client.post(
            "/links/shorten", json={"original_url": "https://cached-stats.com"}
        )
        code = create.json()["short_code"]
        await client.get(f"/links/{code}/stats")  # populates cache
        resp = await client.get(f"/links/{code}/stats")  # from cache
        assert resp.status_code == 200


# ====================== Search ======================


class TestSearch:
    async def test_search(self, client: AsyncClient):
        await client.post(
            "/links/shorten", json={"original_url": "https://searchme.com"}
        )
        resp = await client.get(
            "/links/search", params={"original_url": "https://searchme.com/"}
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    async def test_search_not_found(self, client: AsyncClient):
        resp = await client.get(
            "/links/search", params={"original_url": "https://nope.com"}
        )
        assert resp.status_code == 404

    async def test_search_uses_cache(self, client: AsyncClient):
        await client.post(
            "/links/shorten", json={"original_url": "https://cs.com"}
        )
        url = "https://cs.com/"
        await client.get("/links/search", params={"original_url": url})
        resp = await client.get("/links/search", params={"original_url": url})
        assert resp.status_code == 200


# ====================== Update ======================


class TestUpdate:
    async def test_update(self, client: AsyncClient, auth_headers):
        create = await client.post(
            "/links/shorten",
            json={"original_url": "https://old.com"},
            headers=auth_headers,
        )
        code = create.json()["short_code"]
        resp = await client.put(
            f"/links/{code}",
            json={"original_url": "https://new.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "new.com" in resp.json()["original_url"]

    async def test_update_not_owner(self, client: AsyncClient, auth_headers):
        create = await client.post(
            "/links/shorten",
            json={"original_url": "https://old.com"},
            headers=auth_headers,
        )
        code = create.json()["short_code"]
        # second user
        await client.post(
            "/auth/register", json={"username": "other", "password": "p"}
        )
        r = await client.post(
            "/auth/login", data={"username": "other", "password": "p"}
        )
        other = {"Authorization": f"Bearer {r.json()['access_token']}"}
        resp = await client.put(
            f"/links/{code}",
            json={"original_url": "https://new.com"},
            headers=other,
        )
        assert resp.status_code == 403

    async def test_update_unauthenticated(self, client: AsyncClient):
        create = await client.post(
            "/links/shorten", json={"original_url": "https://old.com"}
        )
        code = create.json()["short_code"]
        resp = await client.put(
            f"/links/{code}", json={"original_url": "https://new.com"}
        )
        assert resp.status_code == 401


# ====================== Delete ======================


class TestDelete:
    async def test_delete(self, client: AsyncClient, auth_headers):
        create = await client.post(
            "/links/shorten",
            json={"original_url": "https://del.com"},
            headers=auth_headers,
        )
        code = create.json()["short_code"]
        resp = await client.delete(f"/links/{code}", headers=auth_headers)
        assert resp.status_code == 204
        # verify deleted
        resp = await client.get(f"/links/{code}", follow_redirects=False)
        assert resp.status_code == 404

    async def test_delete_not_owner(self, client: AsyncClient, auth_headers):
        create = await client.post(
            "/links/shorten",
            json={"original_url": "https://del.com"},
            headers=auth_headers,
        )
        code = create.json()["short_code"]
        await client.post(
            "/auth/register", json={"username": "other2", "password": "p"}
        )
        r = await client.post(
            "/auth/login", data={"username": "other2", "password": "p"}
        )
        other = {"Authorization": f"Bearer {r.json()['access_token']}"}
        resp = await client.delete(f"/links/{code}", headers=other)
        assert resp.status_code == 403

    async def test_delete_unauthenticated(self, client: AsyncClient):
        create = await client.post(
            "/links/shorten", json={"original_url": "https://del.com"}
        )
        code = create.json()["short_code"]
        resp = await client.delete(f"/links/{code}")
        assert resp.status_code == 401


# ====================== Expired history ======================


class TestExpiredHistory:
    async def test_history(self, client: AsyncClient, auth_headers, redis_store):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        create = await client.post(
            "/links/shorten",
            json={"original_url": "https://expire.com", "expires_at": past},
            headers=auth_headers,
        )
        code = create.json()["short_code"]
        redis_store.clear()
        await client.get(f"/links/{code}", follow_redirects=False)  # triggers 410
        resp = await client.get("/links/expired/history", headers=auth_headers)
        assert resp.status_code == 200
        codes = [item["short_code"] for item in resp.json()]
        assert code in codes

    async def test_history_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/links/expired/history")
        assert resp.status_code == 401


# ====================== Auth edge cases ======================


class TestAuthEdgeCases:
    async def test_invalid_token(self, client: AsyncClient):
        headers = {"Authorization": "Bearer invalidtoken"}
        resp = await client.get("/links/expired/history", headers=headers)
        assert resp.status_code == 401

    async def test_token_no_sub(self, client: AsyncClient):
        from jose import jwt as jose_jwt

        token = jose_jwt.encode(
            {"data": "no_sub"}, settings.secret_key, algorithm=settings.algorithm
        )
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get("/links/expired/history", headers=headers)
        assert resp.status_code == 401

    async def test_token_unknown_user(self, client: AsyncClient):
        token = create_access_token({"sub": "nonexistent"})
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get("/links/expired/history", headers=headers)
        assert resp.status_code == 401


from app.config import settings


# ====================== Index / health ======================


class TestIndex:
    async def test_index(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200


# ====================== Cleanup background task ======================


class TestCleanup:
    async def test_cleanup_marks_expired(self, db_session):
        from tests.conftest import TestSessionLocal

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        link = Link(
            short_code="cln1",
            original_url="https://expired.com",
            expires_at=past,
            is_expired=False,
        )
        db_session.add(link)
        await db_session.commit()

        call_count = 0

        async def mock_sleep(_seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError()

        from app.main import cleanup_expired_links

        with patch("asyncio.sleep", new=mock_sleep):
            with patch("app.main.async_session", TestSessionLocal):
                try:
                    await cleanup_expired_links()
                except asyncio.CancelledError:
                    pass

        await db_session.refresh(link)
        assert link.is_expired is True

    async def test_cleanup_deletes_unused(self, db_session):
        from tests.conftest import TestSessionLocal

        old = datetime.now(timezone.utc) - timedelta(days=100)
        link = Link(
            short_code="cln2",
            original_url="https://unused.com",
            is_expired=False,
            last_used_at=old,
        )
        db_session.add(link)
        await db_session.commit()

        call_count = 0

        async def mock_sleep(_seconds):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise asyncio.CancelledError()

        from app.main import cleanup_expired_links

        with patch("asyncio.sleep", new=mock_sleep):
            with patch("app.main.async_session", TestSessionLocal):
                with patch("app.main.settings.unused_links_days", 30):
                    try:
                        await cleanup_expired_links()
                    except asyncio.CancelledError:
                        pass

        result = await db_session.execute(
            select(Link).where(Link.short_code == "cln2")
        )
        assert result.scalar_one_or_none() is None
