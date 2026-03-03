"""Unit tests for pure functions and configuration."""

import string

import pytest
from jose import jwt

from app.auth import hash_password, verify_password, create_access_token
from app.config import Settings, settings
from app.routers.links_router import generate_short_code, _cache_key, _search_cache_key


# ---- generate_short_code ----


class TestGenerateShortCode:
    def test_default_length(self):
        code = generate_short_code()
        assert len(code) == 6

    def test_custom_length(self):
        code = generate_short_code(length=10)
        assert len(code) == 10

    def test_only_alphanumeric(self):
        valid = set(string.ascii_letters + string.digits)
        for _ in range(50):
            assert all(c in valid for c in generate_short_code())

    def test_codes_are_unique(self):
        codes = {generate_short_code() for _ in range(100)}
        assert len(codes) == 100


# ---- password hashing ----


class TestPasswordHashing:
    def test_hash_not_plain(self):
        hashed = hash_password("secret")
        assert hashed != "secret"
        assert hashed.startswith("$2b$")

    def test_verify_correct(self):
        hashed = hash_password("secret")
        assert verify_password("secret", hashed) is True

    def test_verify_wrong(self):
        hashed = hash_password("secret")
        assert verify_password("wrong", hashed) is False


# ---- JWT tokens ----


class TestAccessToken:
    def test_contains_sub(self):
        token = create_access_token({"sub": "alice"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        assert payload["sub"] == "alice"

    def test_has_exp(self):
        token = create_access_token({"sub": "alice"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        assert "exp" in payload

    def test_extra_data_preserved(self):
        token = create_access_token({"sub": "alice", "role": "admin"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        assert payload["role"] == "admin"


# ---- cache key helpers ----


class TestCacheKeys:
    def test_cache_key(self):
        assert _cache_key("abc") == "link:abc"

    def test_search_cache_key(self):
        assert _search_cache_key("https://example.com") == "search:https://example.com"


# ---- Settings.async_database_url ----


class TestSettingsAsyncUrl:
    def test_postgres_prefix(self):
        s = Settings(database_url="postgres://u:p@h/db")
        assert s.async_database_url == "postgresql+asyncpg://u:p@h/db"

    def test_postgresql_prefix(self):
        s = Settings(database_url="postgresql://u:p@h/db")
        assert s.async_database_url == "postgresql+asyncpg://u:p@h/db"

    def test_already_asyncpg(self):
        s = Settings(database_url="postgresql+asyncpg://u:p@h/db")
        assert s.async_database_url == "postgresql+asyncpg://u:p@h/db"
