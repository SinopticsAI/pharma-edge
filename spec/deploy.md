# Деплой Edge

Конвенции как у [`yandex-cloud-functions/.github/workflows`](https://github.com/SinopticsAI/yandex-cloud-functions): селективный деплой по `scr/**`, Environments `preprod` / `prod`. Workflow YAML — [`.github/workflows`](../.github/workflows): селективный деплой `scr/**` в Environments `preprod` / `prod`. Первый локальный подъём — [`infra/README.md`](../infra/README.md).

Terraform не используем.

## Кто пушит и гоняет CI/CD

**Push в remote и прогон GitHub Actions делает владелец репозитория сам.** Агент этого не делает.

Агент пишет код, workflow YAML и локальные скрипты, затем останавливается и говорит, что можно пушить. Не делает `git push`, не запускает workflow (`gh workflow run`, `workflow_dispatch`, `gh api` на Actions) и не деплоит в preprod/prod из своей сессии — даже «чтобы проверить CI».

Локальный подъём по [`infra/README.md`](../infra/README.md) — только если владелец явно попросил.

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
| `YC_SA_JSON_CREDENTIALS` | JSON authorized key деплой-SA (`pharma-edge-sa-ci`). Нужна роль `vpc.user`, иначе CreateVersion: `VPC Network … not found or permission denied` |
| `YC_CLOUD_ID` | `b1gip1vv7381q4bsoaso` |
| `YC_FOLDER_ID` | `b1g07nbj3q7ccru38on0` |
| `YC_SA_PREPROD_ID` | runtime SA preprod (заполнить после provision) |
| `YC_SA_PROD_ID` | runtime SA prod (заполнить после provision) |
| `PHARMA_PLANE_BASE_URL` | публичный URL `api-facade`; cutover / откат |
| `PHARMA_PLANE_API_KEY` | `X-API-Key` на facade; хранить также в Lockbox Plane |
| `PG_HOST` | `c-c9qbferg3hcqjnqkghcp.rw.mdb.yandexcloud.net` — не секрет; CD подставит сам, если пусто |
| `PG_PORT` | `6432` — пулер Odyssey, не 5432 |
| `VPC_NETWORK_ID` | сеть кластера (`enpp5oe8dlepbkjm52rl`); без неё функция до пулера не дотянется |
| `LOCKBOX_PG_ID` | id секрета Lockbox `pharma-edge-pg` (`e6q…`), не id версии и не имя. Ключ payload `pharma_cabinet_password`. CD шлёт `…/latest/…`; нужен `yc-sls-function@v5`, иначе YC ищет версию с id `latest` и отвечает NOT_FOUND |
| `LOCKBOX_HTTP_ID` | секрет `pharma-edge-http`, ключ `PHARMA_EDGE_API_KEY` |
| `LOCKBOX_S3_ID` | секрет `pharma-edge-s3` для presigned upload |
| `PG_CABINET_PASSWORD` | не класть, если есть Lockbox. Пустое значение YC отклоняет как `INVALID_ARGUMENT` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Object Storage досье (или читать из Lockbox в CD) |

Не копировать из Logos: `YOOKASSA_*`, `BITRIX_*`, `AWSCLOUD_API_BASE_URL`.

URL очередей YMQ предпочтительно читать из Lockbox (`pharma-edge-ymq`) в CD, как `logos-bridge-ymq` в `docs/functions-cd-lockbox.md` у Logos. Пока Lockbox нет — переменные `PHARMA_INGEST_QUEUE_URL` и остальные не коммитить.

## Целевые workflow

| Workflow | Триггер | Действие |
| --- | --- | --- |
| CI | push в `feature*` | деплой изменённых `scr/**` в preprod |
| CT | PR в `main` | валидация без `yc deploy` (`compileall`, структура) |
| CD | push в `main`, release, dispatch | деплой изменённых функций в prod. Правка только `spec/**` / README — skip, это не выкат. Полный выкат: Actions → CD → Run workflow |
| detect-changes | reusable | matrix по `git diff` |
| db | изменения в `sql/**` | `psql` apply изнутри сети кластера |

При правке самих workflow-файлов — полный деплой, `max-parallel: 3` из‑за квот `serverless.concurrentFolderOperations`.

Каталог общий с Logos: в нём уже ~40 функций. Edge нужно ещё 14 имён `pharma-edge-*`. Пока квота `serverless.functions.count` не поднята хотя бы до 48, `Create` падает с `RESOURCE_EXHAUSTED`. Пустые `PG_HOST` / `PG_PASSWORD` в env CD не передаём — YC отвечает `INVALID_ARGUMENT`. Пароль кабинета создаёт [`pharma-postgracesql`](https://github.com/SinopticsAI/pharma-postgracesql) (`ensure-postgres.ps1` → Lockbox `pharma-edge-pg`).

Если в annotations CD только `Process completed with exit code 1` — это шаг **Prepare function env**, не `yc deploy`. Значит в GitHub нет `LOCKBOX_PG_ID` и нет запасного `PG_CABINET_PASSWORD`. Environment `prod` секретов не дублирует: класть в **Repository secrets**. Environment `preprod` должен существовать, иначе CI на `feature*` не стартует.

Зелёный CD за 12 секунд с skipped `deploy` / `update-gateway` значит **ничего не выкатили**: в diff не было `scr/**` и workflow-путей. В каталоге из 14 имён `pharma-edge-*` пока 6 (первый прогон упёрся в квоту). Остальные 8 и шлюз `pharma-edge-api-gateway` CD сам не создаст, пока нет квоты, Lockbox `pharma-edge-pg` и (для шлюза) одноразового `deploy-gateway` в [`pharma_env`](https://github.com/SinopticsAI/pharma_env).

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

## Первый подъём волны 1

Отдельный шлюз `pharma-edge-api-gateway` на `pharma-edge.sinoptics.ru`. Статический `pharma-api-gateway` не трогаем.

```powershell
# PostgreSQL: репозиторий pharma-postgracesql (discover → ensure-postgres → apply-sql)
.\infra\scripts\discover.ps1
.\infra\scripts\provision.ps1
.\infra\scripts\deploy-function.ps1
# шлюз и DNS: репозиторий pharma_env (discover → deploy-gateway → deploy-dns)
```

Шлюз создаётся из [`pharma_env`](https://github.com/SinopticsAI/pharma_env) и там же
живёт канон `openapi.template.yaml`. CD этого репозитория только перерисовывает
спеку **существующего** шлюза при изменении `scr/**`; новый шлюз и запись DNS
он не создаёт и падает с явным сообщением, если шлюза нет.

`PHARMA_PLANE_BASE_URL` не обязателен до волны 1b.

## Проверка

- `yc serverless function list --folder-id b1g07nbj3q7ccru38on0` — только `pharma-edge-*`, не `logos-*`.
- SPA ходит только в Edge. Plane для браузера не существует.
- В Lockbox и env нет ключей УКЭП.
