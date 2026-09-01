# Cutover Edge → Plane

Зеркало [`yandex-cloud-functions/docs/v2-plane-cutover.md`](https://github.com/SinopticsAI/yandex-cloud-functions/blob/main/docs/v2-plane-cutover.md). Код функций при переключении **не** меняется.

## Правило

Edge всегда вызывает HTTP facade:

```
POST {PHARMA_PLANE_BASE_URL}/api/v2026-08/cases/{id}/actions/start
Header: X-API-Key
```

Идентификаторы YaWL (`pharma-dossier`, …) Edge не видит. Их знает только `api-facade`.

## Шаги

1. В `pharma-plane` после деплоя facade взять `pharma_plane_base_url` из `reports/plane-config-report.md` (появится вместе с CI).
2. Записать URL в GitHub secret **`PHARMA_PLANE_BASE_URL`** этого репозитория (Environment `preprod`, затем `prod`).
3. Перевыложить функции, которые читают секрет в runtime: как минимум `case_start` (и ingest, когда появится).
4. Сначала гонять `pharma-qualify` / `pharma-dossier` на preprod, потом prod.

## Откат

Откат = смена `PHARMA_PLANE_BASE_URL` на предыдущий здоровый facade **или** пустое значение + стоп трафика `case_start`.

Не откатывать на Logos (`AWSCLOUD_API_BASE_URL`, `logos-processing`). Не звать Workflows из Cloud Function.

После cutover чинить Plane forward (`api-facade`, контейнеры, YaWL) в `pharma-plane`. In-flight executions живут в Plane_YDB: дождаться drain или перезапустить на том же Plane.

## Что не менять при cutover

| Функция / контур | Почему не трогаем |
| --- | --- |
| `cases`, `case_get`, `case_update` | SoR кабинета |
| `dossier_items` | presigned upload |
| `status_ingest`, `calendar_tick` | человек и календарь |
| `filing_artifact` | квитанция ЕПГУ |
| YDB / YMQ / маршруты шлюза | контракт SPA |

Меняется только секрет URL + ключ `X-API-Key`.
