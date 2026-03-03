# Link Shortener — API + Tests

## Запуск сервиса

```bash
docker-compose up --build
```

Сервис будет доступен на `http://localhost:8000`.

## Тестирование

### Установка зависимостей

```bash
pip install -r requirements.txt
```

### Запуск тестов

```bash
# Все тесты (юнит + функциональные)
python -m pytest tests/ -v

# Только юнит-тесты
python -m pytest tests/test_unit.py -v

# Только функциональные тесты
python -m pytest tests/test_api.py -v
```

### Покрытие кода тестами

```bash
# Запуск тестов с замером покрытия
python -m coverage run -m pytest tests/test_unit.py tests/test_api.py

# Текстовый отчёт
python -m coverage report

# HTML-отчёт (сохраняется в htmlcov/)
python -m coverage html
```

**Текущее покрытие: 97%** (53 теста, все проходят).

Конфигурация coverage находится в `.coveragerc` (включает `concurrency = greenlet` для корректного отслеживания async-кода).

### Нагрузочное тестирование

```bash
# Запустить сервис (docker-compose up), затем:
locust -f tests/locustfile.py --host http://localhost:8000
```

Откройте `http://localhost:8089` в браузере для управления нагрузочными тестами.

### Структура тестов

```
tests/
├── conftest.py      # Фикстуры: in-memory SQLite, FakeRedis, TestClient
├── test_unit.py     # Юнит-тесты: generate_short_code, хеширование, JWT, config
├── test_api.py      # Функциональные тесты: все CRUD-операции, auth, redirect, expiry
└── locustfile.py    # Нагрузочные тесты: создание/редирект/поиск/статистика
```

### Что покрыто тестами

| Модуль | Покрытие |
|--------|----------|
| auth.py | 100% |
| config.py | 100% |
| models.py | 100% |
| schemas.py | 100% |
| routers/auth_router.py | 100% |
| routers/links_router.py | 100% |
| main.py | 84% |
| database.py | 80% |
| **TOTAL** | **97%** |
