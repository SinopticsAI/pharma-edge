# Инвентарь Cloud Functions

Одна функция = один zip, `handler(event, context)`, общий `common_log.py`.
Манифест — [`.github/functions-paths.json`](../.github/functions-paths.json),
код — `scr/<id>/`. Общие модули копируются из `scr/_shared/` скриптом
`infra/scripts/sync_shared.py`.

Две особенности этого контура:

- **Все функции ходят в PostgreSQL** и разворачиваются с `--network-id` той же
  сети, что и кластер. Порт 6432, соединение переиспользуется между вызовами.
- **Авторизация не в функции, а на шлюзе.** JWT-авторайзер проверяет токен
  realm `pharma` и передаёт claims в `requestContext.authorizer.jwt`. Функция
  разрешает `sub` в аккаунт через `account_users` и фильтрует по нему каждый
  запрос. Сервисные вызовы (Mastra, Plane) идут по `X-API-Key` с заголовком
  `X-Pharma-Account`.

`item_type` **не** выбирает workflow. Workflow задаёт `settings.workflow`, тип
файла выбирает схему извлечения в Plane.

## 1. Личность и аккаунт

| Функция | Триггер | Назначение |
| --- | --- | --- |
| `identity` | `GET /accounts/me` | Аккаунт, роль и права вызывающего; SPA зовёт сразу после входа |

## 2. Компании и продукты

| Функция | Триггер | Назначение |
| --- | --- | --- |
| `organizations` | `GET/POST /organizations`, `GET/PATCH /organizations/{id}`, `GET/POST .../risk` | Карточка компании, слоты, комплектность по разделам, KYC-гейт |
| `organization_items` | `.../items`, `upload-url`, `confirm-upload`, `download-url`, `promote` | Документы интейка до кейса; presigned GET для просмотра скана; подъём документа продукта в профиль компании |
| `products` | `GET/POST /organizations/{id}/products`, `GET/PATCH /products/{id}`, `.../variants`, `.../approve` | Карточка продукта, варианты классификации, утверждение специалистом и затем клиентом, построение карты `M0`–`M12` |
| `intake` | `/intake/sessions`, `.../messages` | Сессия диалога и журнал, который уходит клиенту вместе с кейсом |

## 3. Кейсы

| Функция | Триггер | Назначение |
| --- | --- | --- |
| `cases` | `GET/POST /cases` | Список и создание кейса вручную; обычный путь — утверждение классификации |
| `case_get` | `GET /cases/{id}` | Карточка, мандат, карта узлов, критический путь |
| `case_update` | `PATCH /cases/{id}` | Квалификация, модели, трек. Нет подачи без мандата и locked models |
| `case_start` | `POST /cases/{id}/actions/start` | Передать подтверждённые файлы в Plane |
| `dossier_items` | `.../items`, `upload-url`, `confirm-upload` | Presigned в бакет РФ |
| `status_ingest` | `GET/POST /cases/{id}/statuses` | Оператор вводит статус с артефактом. SoR, пока нет API госканалов |

## 4. Поиск, время, мост

| Функция | Триггер | Назначение |
| --- | --- | --- |
| `registry_search` | `GET /registry/search` | Кэш реестрового поиска. Не истина, ссылка обязательна |
| `calendar_tick` | таймер ежедневно | Якоря 5 / 30 / 31 / 50 / 140 р.д. Пишет **предложения**, не факты |
| `webhooks` | `POST /webhooks/cases/{id}/items/{itemId}/update`, `.../completed` | Результат извлечения из Plane. Только `X-API-Key`, браузер сюда не ходит |

Вебхук `item_update` делает и автомаппинг: распознанные поля вливаются в драфт
компании или продукта с указанием документа-источника.

Нет `epgu_submit`. Подача остаётся за человеком с УКЭП.

## 5. Чего в Edge нет

Функции `intake_chat` не существует и не будет: политика диалога живёт в
Mastra ([`pharma-agent`](https://github.com/SinopticsAI/pharma-agent)), Edge
остаётся системой записи и набором инструментов агента. Детерминированные
правила — слияние драфта, комплектность, слоты, карта узлов — остаются здесь,
в `scr/_shared/edge_intake.py`: это валидация, её нельзя отдавать модели.

## 6. Дерево `scr/`

```
scr/
  _shared/            common_log, edge_http, edge_pg, edge_domain, edge_intake, edge_plane
  identity/
  organizations/
  organization_items/
  products/
  intake/
  cases/
  case_get/
  case_update/
  case_start/
  dossier_items/
  status_ingest/
  registry_search/
  webhooks/
  calendar_tick/
```

OpenAPI шлюза — [`infra/gateway/openapi.template.yaml`](../infra/gateway/openapi.template.yaml),
копия канона из [`pharma_env`](https://github.com/SinopticsAI/pharma_env).
Там же первая контейнерная интеграция: `/chat/{agentId}` уходит в контейнер
Mastra через `serverless_containers`. Пока контейнера нет, рендер подставляет
заглушку `503`, и шлюз поднимается без агента.
