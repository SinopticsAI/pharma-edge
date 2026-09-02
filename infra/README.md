# Yandex Cloud: pharma-edge.sinoptics.ru

Отдельный API Gateway `pharma-edge-api-gateway`. Статический портал
`pharma.sinoptics.ru` (`pharma-api-gateway`) **не трогаем** — как
`orders-api-gateway` не трогает `sinoptics-api-gateway`.

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
| [scripts/ensure-postgres.ps1](scripts/ensure-postgres.ps1) | Кластер: реплика, авторост диска, защита от удаления, доступ `serverless`, правило 6432, базы `pharma_cabinet` и `pharma_agent` |
| [scripts/apply-sql.ps1](scripts/apply-sql.ps1) | DDL + сид аккаунта и организаций |
| [scripts/deploy-function.ps1](scripts/deploy-function.ps1) | Cloud Functions волны 1 + timer `calendar_tick` |
| [scripts/deploy-gateway.ps1](scripts/deploy-gateway.ps1) | `pharma-edge-api-gateway` + spec |
| [scripts/deploy-dns.ps1](scripts/deploy-dns.ps1) | CNAME `pharma-edge.sinoptics.ru.` |

Порядок первого подъёма:

```powershell
.\infra\scripts\discover.ps1
.\infra\scripts\provision.ps1
.\infra\scripts\ensure-postgres.ps1
.\infra\scripts\apply-sql.ps1   # изнутри сети кластера: публичного хоста нет
.\infra\scripts\deploy-function.ps1
.\infra\scripts\deploy-gateway.ps1
.\infra\scripts\deploy-dns.ps1
```

Живые URL после DNS:

- API: `https://pharma-edge.sinoptics.ru/cases`
- поиск: `https://pharma-edge.sinoptics.ru/registry/search`
- статика (чужая): `https://pharma.sinoptics.ru/`

Заголовок `X-API-Key` обязателен. Ключ лежит в Lockbox `pharma-edge-http`.
