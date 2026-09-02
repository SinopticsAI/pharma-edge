# Yandex Cloud: pharma-edge.sinoptics.ru

Отдельный API Gateway `pharma-edge-api-gateway`. Статический портал
`pharma.sinoptics.ru` (`pharma-api-gateway`) **не трогаем** — как
`orders-api-gateway` не трогает `sinoptics-api-gateway`.

Канон шлюза и DNS — [`pharma_env`](https://github.com/SinopticsAI/pharma_env).
Здесь шлюз только пересобирается после деплоя функций; создание шлюза,
привязка домена и CNAME делаются оттуда.

Ключ `yandex_key.env` в корне — только bootstrap `yc`. Не коммитить.
Профиль:

```powershell
yc config profile create pharma-edge
yc config set service-account-key yandex_key.env
yc config set cloud-id b1gip1vv7381q4bsoaso
yc config set folder-id b1g07nbj3q7ccru38on0
yc config profile activate pharma-edge
```

Скопировать [account.env.example](account.env.example) → `account.env`
и заполнить id после discovery.

| Скрипт | Что делает |
| --- | --- |
| [scripts/discover.ps1](scripts/discover.ps1) | Сети, сертификат, DNS, уже созданные id |
| [scripts/provision.ps1](scripts/provision.ps1) | SA, бакет `pharma-dossier`, YMQ+DLQ, Lockbox |
| [scripts/ensure-postgres.ps1](scripts/ensure-postgres.ps1) | **копия.** Канон — [`pharma-postgracesql`](https://github.com/SinopticsAI/pharma-postgracesql): реплика, авторост, serverless, базы |
| [scripts/apply-sql.ps1](scripts/apply-sql.ps1) | **копия.** Канон DDL — `pharma-postgracesql/sql` |
| [scripts/deploy-function.ps1](scripts/deploy-function.ps1) | Cloud Functions волны 1 + timer `calendar_tick` |
| [scripts/deploy-gateway.ps1](scripts/deploy-gateway.ps1) | **копия.** Канон — [`pharma_env`](https://github.com/SinopticsAI/pharma_env): шлюз, spec, привязка домена |
| [scripts/deploy-dns.ps1](scripts/deploy-dns.ps1) | **копия.** Канон CNAME — `pharma_env` |
| [gateway/openapi.template.yaml](gateway/openapi.template.yaml) | **копия.** Канон маршрутов — `pharma_env/infra/gateway` |

Порядок первого подъёма:

```powershell
# сначала канон кластера: D:\_sinoptics_git\pharma-postgracesql
#   .\infra\scripts\discover.ps1
#   .\infra\scripts\ensure-postgres.ps1
#   .\infra\scripts\apply-sql.ps1
.\infra\scripts\discover.ps1
.\infra\scripts\provision.ps1
.\infra\scripts\deploy-function.ps1
# затем шлюз и DNS: D:\_sinoptics_git\pharma_env
#   .\infra\scripts\discover.ps1
#   .\infra\scripts\deploy-gateway.ps1
#   .\infra\scripts\deploy-dns.ps1
```

Живые URL после DNS:

- API: `https://pharma-edge.sinoptics.ru/cases`
- поиск: `https://pharma-edge.sinoptics.ru/registry/search`
- статика (чужая): `https://pharma.sinoptics.ru/`

Заголовок `X-API-Key` обязателен. Ключ лежит в Lockbox `pharma-edge-http`.
