# Деплой Edge

Конвенции как у [`yandex-cloud-functions/.github/workflows`](https://github.com/SinopticsAI/yandex-cloud-functions): селективный деплой по `scr/**`, Environments `preprod` / `prod`. Workflow YAML в этом репозитории ещё не заведены — это спецификация, по которой их писать.

Terraform не используем.

## Целевой каталог

| Параметр | Значение |
| --- | --- |
| Cloud | `b1gip1vv7381q4bsoaso` |
| Folder | `b1g07nbj3q7ccru38on0` |
| Регион | `ru-central1` |
| Бакет статики (чужой) | `pharma-sinoptics-ru` — не трогать |
| Бакет досье (свой) | `pharma-dossier` (имя уточняется при provision) |

Сервисные аккаунты — [`iam.yml`](../iam.yml). Не брать `logos-*` и не класть в репо `yandex_key.env`.

## GitHub Environments

Settings → Environments:

- `preprod`
- `prod`

## Секреты репозитория

| Secret | Назначение |
| --- | --- |
| `YC_SA_JSON_CREDENTIALS` | JSON authorized key деплой-SA (`pharma-edge-sa-ci`) |
| `YC_CLOUD_ID` | `b1gip1vv7381q4bsoaso` |
| `YC_FOLDER_ID` | `b1g07nbj3q7ccru38on0` |
| `YC_SA_PREPROD_ID` | runtime SA preprod (заполнить после provision) |
| `YC_SA_PROD_ID` | runtime SA prod (заполнить после provision) |
| `PHARMA_PLANE_BASE_URL` | публичный URL `api-facade`; cutover / откат |
| `PHARMA_PLANE_API_KEY` | `X-API-Key` на facade; хранить также в Lockbox Plane |
| `YDB_ENDPOINT` | Document API endpoint |
| `YDB_DATABASE` | путь БД |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Object Storage досье (или читать из Lockbox в CD) |

Не копировать из Logos: `YOOKASSA_*`, `BITRIX_*`, `AWSCLOUD_API_BASE_URL`.

URL очередей YMQ предпочтительно читать из Lockbox (`pharma-edge-ymq`) в CD, как `logos-bridge-ymq` в `docs/functions-cd-lockbox.md` у Logos. Пока Lockbox нет — переменные `PHARMA_INGEST_QUEUE_URL` и остальные не коммитить.

## Целевые workflow

| Workflow | Триггер | Действие |
| --- | --- | --- |
| CI | push в `feature*` | деплой изменённых `scr/**` в preprod |
| CT | PR в `main` | валидация без `yc deploy` (`compileall`, структура) |
| CD | push в `main`, release, dispatch | деплой изменённых функций в prod |
| detect-changes | reusable | matrix по `git diff` |
| ydb | изменения в `sql/**` | `ydb-cli` apply |

При правке самих workflow-файлов — полный деплой, `max-parallel: 3` из‑за квот `serverless.concurrentFolderOperations`.

Поток:

```
feature push → CI (preprod)
PR → CT
merge → main → CD (prod)
```

## Локальный профиль yc (не коммитить ключ)

```powershell
yc config profile create pharma-edge
yc config set cloud-id b1gip1vv7381q4bsoaso
yc config set folder-id b1g07nbj3q7ccru38on0
yc config profile activate pharma-edge
```

Ключ SA передаётся через `yc config set service-account-key <файл вне репо>`.

## Первый подъём волны 1 (когда появится код)

1. Provision SA из `iam.yml`.
2. Создать бакет досье (private) и YDB-таблицы из [`ydb.md`](ydb.md).
3. Создать очереди YMQ + DLQ.
4. Выложить `cases*`, `dossier_items`, `status_ingest`, `calendar_tick`, `registry_search`.
5. Навесить маршруты на API Gateway (отдельная spec, не ломая статику `pharma.sinoptics.ru`).
6. `PHARMA_PLANE_BASE_URL` не обязателен до волны 1b.

## Проверка

- `yc serverless function list --folder-id b1g07nbj3q7ccru38on0` — только `pharma-edge-*`, не `logos-*`.
- SPA ходит только в Edge. Plane для браузера не существует.
- В Lockbox и env нет ключей УКЭП.
