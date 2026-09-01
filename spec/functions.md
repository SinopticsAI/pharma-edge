# Инвентарь Cloud Functions

Одна функция = один zip, `handler(event, context)`, общий `common_log.py`, идемпотентность через YDB. Имена зеркалят Logos-мост, path prefix — `cases`, не `verifications`.

`item_type` **не** выбирает workflow (правило Logos SCRUM-148). Workflow задаёт `settings.workflow`. Тип файла выбирает схему извлечения в Plane.

Манифест волны 1: [`.github/functions-paths.json`](../.github/functions-paths.json). Код — `scr/<id>/`. Общие модули копируются из `scr/_shared/` скриптом `infra/scripts/sync_shared.py`.

## 1. Ядро кабинета

| Функция | Триггер | Назначение | Волна |
| --- | --- | --- | --- |
| `cases` | `POST /cases` | Создать кейс (одно будущее РУ) | 1 |
| `case_get` | `GET /cases/{id}` | Карточка + стадия + маска полей для SPA | 1 |
| `case_update` | `PATCH /cases/{id}` | Квалификация, модели, трек. Нет подачи без мандата и locked models | 1 |
| `case_start` | `POST /cases/{id}/actions/start` | Квота → `processing` → HTTP в facade. `409` если уже processing | 1b |
| `dossier_items` | `POST .../items/upload-url`, confirm | Presigned в бакет РФ | 1 |
| `dossier_item_get` | `GET .../items/{itemId}` | Мета + `parced_data` после Plane | 1b |
| `case_report` | `GET .../report` | Сводка агентов комплектности | 1b |

## 2. Поиск и статусы

| Функция | Триггер | Назначение | Волна |
| --- | --- | --- | --- |
| `registry_search` | HTTP, синхронно | Поиск аналогов: виджет ЕЛК, опционально ГРЛС. TTL-кэш в `search_hits` | 1 (ручной) |
| `registry_poller` | таймер `*/30 * * * ? *` | Обход кейсов в `registry` / `expertise`. Пишет **proposal**, не факт | 3 |
| `fsa_lookup` | HTTP | Область аккредитации лаборатории | 3 |
| `status_ingest` | `POST /cases/{id}/statuses` | Оператор вводит статус + артефакт. SoR, пока нет API ЕЛК | 1 |
| `mail_poller` | таймер | Письма РЗН / Минздрав / лаборатория. Курсор в YDB. Не отвечает регулятору | 2 |
| `calendar_tick` | таймер ежедневно | Якоря 5 / 30 / 31 / 50 / 140 р.д. | 1 |
| `hermes_dispatch` | YMQ `pharma-intel` | Задача разведки **без досье** | 2b |
| `hermes_webhook` | HTTP с VPS | Finding → `proposed` до confirm в `web-ru` | 2b |

## 3. Подача — пакет и артефакт

| Функция | Триггер | Назначение | Волна |
| --- | --- | --- | --- |
| `filing_package` | `POST /cases/{id}/filing-packages` | Zip/опись S3 «версия в подаче». Не вызывает ЕПГУ | 2 |
| `filing_artifact` | `POST /cases/{id}/filing-artifacts` | Квитанция ЕПГУ, номер заявления, pdf 201н | 2 |
| `duty_record` | HTTP / ledger | Факт уплаты пошлины (pass-through), не эквайринг регулятора | 2 |

Нет `epgu_submit`.

## 4. Мост Plane → Edge

| Функция | Триггер | Назначение | Волна |
| --- | --- | --- | --- |
| `webhook_item_update` | `POST /webhooks/cases/{id}/items/{itemId}/update` | `parced_data` item; может уйти в YMQ | 1b |
| `webhook_case_completed` | `POST /webhooks/cases/{id}/completed` | Финал / прогресс ростера | 1b |
| `payload_upload_url` | `POST /cases/{id}/items/{itemId}/payload-upload-url` | Claim-check, если тело > порога YMQ | 1b |

## 5. Очереди YMQ

| Очередь | Потребитель | Назначение |
| --- | --- | --- |
| `pharma-ingest` | будущий ingest / start | Старт пайплайна |
| `pharma-item-update` | `webhook_item_update` | Буфер вебхуков item |
| `pharma-completed` | `webhook_case_completed` | Буфер completed |
| `pharma-intel` | `hermes_dispatch` | Разведка без досье |

У каждой очереди — DLQ. Идемпотентность: таблица `processed_messages` `(consumer, message_id)`.

## 6. Будущее дерево `scr/`

```
scr/
  cases/
  case_get/
  case_update/
  case_start/
  dossier_items/
  registry_search/
  registry_poller/
  fsa_lookup/
  status_ingest/
  mail_poller/
  calendar_tick/
  filing_package/
  filing_artifact/
  hermes_dispatch/
  hermes_webhook/
  webhook_item_update/
  webhook_case_completed/
doc/api-gateway-openapi.yaml
sql/
```

OpenAPI волны 1 — [`infra/gateway/openapi.template.yaml`](../infra/gateway/openapi.template.yaml) на отдельном `pharma-edge-api-gateway`. Существующий `pharma-api-gateway` остаётся только статикой; бакет досье не смешивается со статикой.
