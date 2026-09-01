# pharma-edge

Edge-слой портала государственной регистрации ЛП и МИ: HTTP API Gateway, Cloud Functions, YDB SoR кабинета, YMQ/DLQ, таймеры-поллеры.

Обработка файлов (OCR, комплектность, агенты) живёт в [`SinopticsAI/pharma-plane`](https://github.com/SinopticsAI/pharma-plane). Разведка без досье — в `hostingervps_hermes` (`pharma_intel`). Статика `pharma.sinoptics.ru` — в [`pharma_cert/infra`](https://github.com/SinopticsAI) (демо-бакет, не бакет досье).

**Дата среза спецификации:** 1 сентября 2026 года.  
**Продуктовый источник:** [`pharma_cert/portal/view/07-backendnoe.md`](https://github.com/SinopticsAI).  
**Конвенции CI/CD:** [`SinopticsAI/yandex-cloud-functions`](https://github.com/SinopticsAI/yandex-cloud-functions) (Logos Edge). Этот репозиторий **не** делит квоту и биллинг с Logos.

На этом этапе в репозитории только спецификации конфигурации и деплоя. Кода функций и живого `yc apply` нет.

## Что владеет Edge

- карточки кейсов для SPA (`cases` ≈ `verifications` у Logos);
- presigned upload досье в бакет РФ;
- ручной ввод статусов и квитанций ЕПГУ;
- календарь нормативных сроков;
- мост в Plane: `POST {PHARMA_PLANE_BASE_URL}/api/v2026-08/cases/{id}/actions/start` + `X-API-Key`.

## Чего Edge не делает

- не вызывает Yandex Workflows напрямую;
- не гоняет OCR/LLM дольше лимита функции;
- не подписывает УКЭП и не подаёт на ЕПГУ (`610095` / `630782`);
- не хранит ключи УКЭП / МЧД / пароли ЕСИА.

Откат Plane = смена секрета `PHARMA_PLANE_BASE_URL`. Подробности: [`spec/cutover.md`](spec/cutover.md).

## Документы

| Файл | Содержание |
| --- | --- |
| [`spec/design.md`](spec/design.md) | Разрез слёв и волны внедрения |
| [`spec/functions.md`](spec/functions.md) | Инвентарь Cloud Functions |
| [`spec/ydb.md`](spec/ydb.md) | Таблицы SoR |
| [`spec/deploy.md`](spec/deploy.md) | CI/CD, секреты, Environments |
| [`spec/cutover.md`](spec/cutover.md) | Переключение на Plane и откат |
| [`iam.yml`](iam.yml) | Черновик сервисных аккаунтов |

## Каталог Yandex Cloud

Тот же folder, что у демо `pharma.sinoptics.ru`:

- Cloud: `b1gip1vv7381q4bsoaso`
- Folder: `b1g07nbj3q7ccru38on0`

Отдельные SA с префиксом `pharma-edge-`. Не переиспользовать `logos-*` и ключ `yandex_key.env` из `pharma_cert`.

## Дисклеймер

Это не инструкция обойти УКЭП и не обещание автоподачи. Бэкенд ищет, готовит пакет и принимает подтверждённые статусы. Заявитель на ЕПГУ — рабочее место РФ.
