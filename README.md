# pharma-edge

Edge-слой портала государственной регистрации ЛП и МИ: HTTP API Gateway, Cloud Functions, PostgreSQL SoR кабинета, YMQ/DLQ, таймеры-поллеры.

Обработка файлов (OCR, комплектность, агенты) живёт в [`SinopticsAI/pharma-plane`](https://github.com/SinopticsAI/pharma-plane). Диалог интейка — в [`SinopticsAI/pharma-agent`](https://github.com/SinopticsAI/pharma-agent) (Mastra за этим же шлюзом). Разведка без досье — в `hostingervps_hermes` (`pharma_intel`). Статика `pharma.sinoptics.ru` — в [`pharma_cert/infra`](https://github.com/SinopticsAI) (демо-бакет, не бакет досье).

**Дата среза спецификации:** 2 сентября 2026 года.  
**Продуктовый источник:** [`pharma_cert/portal/view/07-backendnoe.md`](https://github.com/SinopticsAI).  
**Конвенции CI/CD:** [`SinopticsAI/yandex-cloud-functions`](https://github.com/SinopticsAI/yandex-cloud-functions) (Logos Edge). Этот репозиторий **не** делит квоту и биллинг с Logos.

Волна 1 в репозитории: Cloud Functions в `scr/`, DDL в `sql/`, отдельный шлюз в `infra/`. Первый подъём — [`infra/README.md`](infra/README.md).

## Что владеет Edge

- аккаунты, компании, продукты, кейсы и их документы — база `pharma_cabinet`;
- presigned upload досье и документов интейка в бакет РФ;
- инварианты: специалист утверждает классификацию раньше клиента, нет подачи без мандата, запрещённый вариант нельзя выбрать;
- ручной ввод статусов и квитанций ЕПГУ;
- календарь нормативных сроков;
- мост в Plane: `POST {PHARMA_PLANE_BASE_URL}/api/v2026-08/cases/{id}/actions/start` + `X-API-Key`.

## Чего Edge не делает

- не ведёт диалог: политика разговора живёт в `pharma-agent`, здесь только детерминированные правила;
- не вызывает Yandex Workflows напрямую;
- не гоняет OCR/LLM дольше лимита функции;
- не подписывает УКЭП и не подаёт на ЕПГУ (`610095` / `630782`);
- не хранит ключи УКЭП / МЧД / пароли ЕСИА;
- не отдаёт сырые источники KYC: наружу уходит только уровень риска и обезличенное обоснование.

## Вход

Браузер приходит с токеном Keycloak realm `pharma`; подпись, издателя и
аудиторию проверяет JWT-авторайзер шлюза, а функция читает проверенные claims и
разрешает `sub` в аккаунт через `account_users`. `X-API-Key` в браузере больше
не живёт — это служебный ключ для Mastra и вебхуков Plane.

Откат Plane = смена секрета `PHARMA_PLANE_BASE_URL`. Подробности: [`spec/cutover.md`](spec/cutover.md).

## Документы

| Файл | Содержание |
| --- | --- |
| [`spec/design.md`](spec/design.md) | Разрез слоёв и волны внедрения |
| [`spec/functions.md`](spec/functions.md) | Инвентарь Cloud Functions |
| [`spec/db.md`](spec/db.md) | Таблицы SoR в PostgreSQL |
| [`spec/deploy.md`](spec/deploy.md) | CI/CD, секреты, Environments |
| [`spec/cutover.md`](spec/cutover.md) | Переключение на Plane и откат |
| [`iam.yml`](iam.yml) | Черновик сервисных аккаунтов |
| [`infra/README.md`](infra/README.md) | Отдельный `pharma-edge-api-gateway` на `pharma-edge.sinoptics.ru` |

## Каталог Yandex Cloud

Тот же folder, что у демо `pharma.sinoptics.ru`:

- Cloud: `b1gip1vv7381q4bsoaso`
- Folder: `b1g07nbj3q7ccru38on0`

Отдельные SA с префиксом `pharma-edge-`. Не переиспользовать `logos-*` и ключ `yandex_key.env` из `pharma_cert`.

## Дисклеймер

Это не инструкция обойти УКЭП и не обещание автоподачи. Бэкенд ищет, готовит пакет и принимает подтверждённые статусы. Заявитель на ЕПГУ — рабочее место РФ.
