# Backend model redeploy design

## Goal

Добавить штатный backend flow для пересоздания RunPod endpoint'а модели без ручных `docker exec` обходов.

## Chosen approach

Добавляем отдельный admin route:

`POST /admin/models/{model_id}/redeploy`

Почему отдельный route:
- поведение явное и предсказуемое;
- не меняет смысл существующего `/deploy`;
- подходит для уже активных моделей, когда меняются `gpu_type`, `gpu_count`, `max_context_length` или deploy-конфиг.

## API contract

### Request
Без body.

### Response
Успех:

```json
{
  "detail": "Model redeployed",
  "endpoint_id": "<new-runpod-endpoint-id>"
}
```

Ошибки:
- `404` — модель не найдена;
- `500` — удаление старого endpoint или создание нового endpoint завершилось ошибкой.

## Backend flow

1. Загрузить `LlmModel` по `model_id`.
2. Если модель не найдена — вернуть `404`.
3. Поставить `model.status = "deploying"` и сделать `commit`.
4. Если у модели есть `runpod_endpoint_id`:
   - вызвать `delete_endpoint(model.runpod_endpoint_id)`;
   - после успешного удаления записать `model.runpod_endpoint_id = None` и сделать `commit`.
5. Вызвать `create_endpoint(...)`, используя текущие значения из БД:
   - `name = f"unch-{model.slug}"`
   - `gpu_type = model.gpu_type`
   - `model_name = model.hf_repo`
   - `params_b = float(model.params_b or 0)`
   - `max_model_len = model.max_context_length or 4096`
   - `gpu_count = model.gpu_count or 1`
   - `db = db`
6. Сохранить новый `runpod_endpoint_id` из ответа RunPod.
7. Поставить `model.status = "active"` и сделать `commit`.
8. Вернуть success response.

## Failure behavior

Если любой шаг после перевода в `deploying` падает:
- установить `model.status = "inactive"`;
- сохранить это в БД;
- вернуть `HTTP 500` с текстом ошибки.

## Notes on deletion order

Удаляем старый endpoint **до** создания нового. Это соответствует текущей квоте RunPod и нашему существующему механизму `_ensure_endpoint_quota(db)`.

Это означает короткое окно, в котором модель будет в статусе `deploying` и без активного endpoint'а. Для административного redeploy это приемлемо и проще, чем параллельное переключение между двумя endpoint'ами.

## Files to change

- `backend/app/routers/admin.py`

Дополнительные схемы не нужны: endpoint без request body и с простым dict-ответом, как текущий `/deploy`.

## Testing

1. Вызвать новый `/admin/models/{id}/redeploy` для активной модели.
2. Проверить, что:
   - старый endpoint удалён;
   - новый endpoint создан;
   - `runpod_endpoint_id` обновлён в БД;
   - `status = active`.
3. Проверить неуспешный сценарий:
   - при ошибке создания endpoint'а модель получает `status = inactive`.

## Out of scope

- zero-downtime switchover;
- асинхронная очередь деплоя;
- audit log/history redeploy операций;
- изменение существующего `/deploy` route.
