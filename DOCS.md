# Link Shortener

Сервис сокращения ссылок. FastAPI + PostgreSQL + Redis.

## Как запустить

```bash
docker-compose up --build
```

Откроется на http://localhost:8000, документация на http://localhost:8000/docs

## БД

Две таблицы: `users` и `links`.

`users` — id, username, hashed_password, created_at

`links` — id, short_code, original_url, created_at, expires_at, last_used_at, click_count, is_expired, owner_id (FK на users, может быть NULL если создал аноним)

## Эндпоинты

### Авторизация

**Регистрация**
```
POST /auth/register
{"username": "user1", "password": "secret123"}
```

**Логин** — возвращает JWT токен
```
POST /auth/login (form-data: username, password)
```
Токен передавать в хедере `Authorization: Bearer <token>`

### Ссылки

**Создать короткую ссылку** (токен опционален)
```
POST /links/shorten
{"original_url": "https://example.com/long", "custom_alias": "myalias", "expires_at": "2025-12-31T23:59:00Z"}
```
custom_alias и expires_at необязательны. Без токена ссылка анонимная — удалить/обновить не получится.

**Перейти по ссылке** — делает 307 редирект
```
GET /links/{short_code}
```

**Удалить** (нужен токен, только свои)
```
DELETE /links/{short_code}
```

**Обновить URL** (нужен токен, только свои)
```
PUT /links/{short_code}
{"original_url": "https://example.com/new"}
```

**Статистика**
```
GET /links/{short_code}/stats
```
Возвращает original_url, created_at, click_count, last_used_at, expires_at.

**Поиск по оригинальному URL**
```
GET /links/search?original_url=https://example.com
```

**История истекших ссылок** (нужен токен)
```
GET /links/expired/history
```

## Кэширование

Redis кэширует:
- редиректы (чтобы не дергать БД на каждый переход)
- статистику
- результаты поиска

При удалении/обновлении ссылки кэш чистится. TTL по умолчанию 300 сек (настраивается через `CACHE_TTL`).

## Доп. функции

1. Автоудаление неиспользуемых ссылок — через env `UNUSED_LINKS_DAYS` (по умолчанию 0 = выключено)
2. История истекших ссылок — `GET /links/expired/history`

## Env переменные

Смотри `.env.example`. Основные:
- `DATABASE_URL` — подключение к PostgreSQL
- `REDIS_URL` — подключение к Redis
- `SECRET_KEY` — секрет для JWT
- `CACHE_TTL` — TTL кэша в секундах
- `UNUSED_LINKS_DAYS` — через сколько дней без использования удалять ссылку (0 = не удалять)
