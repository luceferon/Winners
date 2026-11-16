# Решения: удаление модуля парсинга и симулятора

## Запрос

Убрать из приложения модуль парсинга ставок (поиск событий у внешних
провайдеров, авто-расчёт результатов, внутренний симулятор матчей), а также
кнопки синхронизации и отвязки события в истории ставок. Симулятор работал не
так, как нужно, и усложнял интерфейс без практической пользы.

## Подтверждённые решения

- Полностью удалить подсистему парсинга: директорию `app/parsers/`, роутер
  `app/api/parsing.py`, модели `Event` и `ParseLog`, планировщик
  (`app/scheduler.py` с APScheduler), HTTP-клиент с retry/кэшем.
- Убрать из `Bet` поля, связанные с парсингом: `event_id`, `auto_settled`,
  `needs_review`, `review_reason`, `match_confidence`, `last_sync_at`,
  а также связь `event`.
- Удалить эндпоинты `/api/bets/{id}/sync`, `/link`, `/unlink` и
  все маршруты `/api/parsing/*` (status, run, search, sports, logs).
- Из `DEFAULT_SETTINGS` убрать `match_threshold`, `auto_settle`,
  `live_window_minutes`, `parse_batch_limit`, а также все API-ключи
  провайдеров и `default_provider`.
- `Bet.as_dict()` больше не принимает `with_event` и не возвращает поля события.
- Ставки вводятся и рассчитываются **исключительно вручную**: пользователь
  сам отмечает результат (`won`/`lost`/`push`/`cancelled`), выплата и
  прибыль считаются автоматически по коэффициенту и сумме.
- Сохранены: одиночные ставки и экспрессы (с расчётом по ногам), статистика
  с графиками, источники с автоматической надёжностью, банкролл, настройки.
- Legacy-колонки в `sources` (`kind`, `provider_key`, `api_key`, `reliability`)
  оставлены в БД для совместимости, но не используются и не отображаются.

## Подход

Удаление проводилось послойно от зависимостей к зависимым:
1. Удалены тесты парсера (`test_engine.py`, `test_offline_provider.py`,
   `test_matching.py`, `test_results.py`).
2. Удалён код парсера (`app/parsers/`, `app/api/parsing.py`, `scheduler.py`).
3. Очищены модели (`Event`, `ParseLog`, поля парсинга в `Bet`).
4. Очищены сервисы и роутеры от ссылок на парсинг (`joinedload(Bet.event)`,
   `mark_needs_review`, `/sync`, `/unlink`).
5. Обновлены фронтенд-виды (`history.js`, `add.js`, `settings.js`, `api.js`).
6. Исправлены тесты (`test_bets_service.py`, `test_settings_service.py`,
   `test_api.py`) и прогнан `pytest`.

## Проверки

- `python -m pytest tests -q` → **76 passed**.
- `python -c "import app.main"` → без ошибок.
- grep по `app/`, `web/js/`, `tests/` на `ParseLog|event_id|needs_review|
  auto_settled|syncBet|with_event|/sync|/unlink` → совпадений нет.
- Настройки больше не содержат `auto_settle`, сохранение не падает с
  `SettingsError: Неизвестная настройка`.

## Связанные хроники

- [0001 — упрощение источников ставок](./0001__2026-11-16__source-simplification.md):
  ранее из источников убрали API-ключ, провайдера парсинга, тип и ручную
  надёжность. После удаления парсера эти legacy-поля окончательно потеряли
  смысл, но остались в схеме БД.
