from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/linkshortener"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "super-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    # Unused links cleanup: delete links not used for N days (0 = disabled)
    unused_links_days: int = 0
    cache_ttl: int = 300  # seconds

    model_config = {"env_file": ".env"}


settings = Settings()
