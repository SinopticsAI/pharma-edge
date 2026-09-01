# YDB SoR кабинета

Отдельный префикс таблиц. Не смешивать с `verifications` / `logos_*`. Канон DDL — спецификация здесь; apply позже через `ydb-cli` (как `ydb/**` в Logos Edge) или пакет `yandex-db`.

Plane пишет только в `plane_*`. Писать в таблицы SPA Plane не имеет права.

## Таблицы Edge

| Таблица | Аналог Logos | Смысл |
| --- | --- | --- |
| `organizations` | org в биллинге | РФ-УПП, компания КНР |
| `mandates` | — | договор, доверенность, апостиль, ЕСИА/УКЭП/МЧД как атрибуты |
| `products` | — | семейство моделей, NMPA, площадки |
| `cases` | `verifications` | одно РУ, `track`, `risk_class`, `current_stage` |
| `case_items` | `verification_items` | файлы досье, `item_type`, `parced_data` |
| `roadmap_items` | — | нормативные vs проектные сроки |
| `search_hits` | — | кэш реестровых поисков |
| `status_entries` | — | ввод оператора + `artifact_s3` |
| `status_proposals` | — | поллер / Hermes, ждут confirm |
| `filing_packages` | — | неизменяемая «версия в подаче» |
| `filing_artifacts` | — | квитанции ЕПГУ |
| `regulator_requests` | — | запрос, `due_working_days`, ответ |
| `ledger_lines` | payments (другая семантика) | pass-through vs commission |
| `case_routing` | `logos_routing` | внешний id (письмо, номер ЕПГУ) → `case_id` |
| `pipeline_runs` | та же | журнал запусков Plane |
| `pipeline_events` | та же | стадии моста |
| `processed_messages` | та же | идемпотентность YMQ `(consumer, message_id)` |

## Инварианты

- кейс не переходит к подаче без завершённого мандата и закрытого списка моделей;
- «версия в подаче» неизменяема; правка создаёт новую версию;
- строка комиссии в `ledger_lines` — отдельный тип записи;
- `status_proposals` не становятся фактом без `status_ingest` / confirm оператора.

## Plane_YDB (не этот репозиторий)

В `pharma-plane`: `plane_cases`, `plane_case_items`, `plane_agent_reports`. Тот же кластер YDB по умолчанию, другой префикс. DDL — в спецификации Plane.

## Секреты подключения

`YDB_ENDPOINT` и `YDB_DATABASE` — GitHub Secrets / Lockbox, не в git. Folder: `b1g07nbj3q7ccru38on0`.
