# Strict OpenAI-Compatible API Design

## Goal

Сделать `/v1/chat/completions` и его streaming-поведение строго совместимыми с OpenAI API, без кастомных SSE-объектов, которые ломают внешних клиентов вроде `opencode`.

## Chosen approach

Выбран **Вариант A**:
- `/v1/chat/completions` должен отдавать только OpenAI-compatible response/stream payloads;
- кастомные status events (`object: "status"`) полностью убираются из OpenAI endpoint;
- статусы `cold / warming_up / throttled / ready` остаются только в отдельном endpoint:
  - `GET /v1/models/{model_slug}/status`

## Root cause being addressed

Сейчас streaming path в `backend/app/services/proxy_service.py` отправляет промежуточные SSE-события такого вида:

```json
{
  "object": "status",
  "status": "idle",
  "message": "Preparing worker...",
  "estimated_wait": 60
}
```

Это не OpenAI-совместимый chunk. Клиенты, которые ждут только:
- `chat.completion.chunk` с `choices`
- или `error`

падают на type validation. Именно это происходит в `opencode`.

## API contract after change

### `/v1/chat/completions`

#### Non-streaming
Без изменений по контракту: обычный OpenAI-compatible JSON response.

#### Streaming
Должен отдавать только:
1. standard initial assistant role chunk;
2. zero or more standard `chat.completion.chunk` objects with `choices`;
3. final chunk with `finish_reason`;
4. `data: [DONE]`

Никаких промежуточных custom status objects быть не должно.

## Status handling

Информация о состоянии worker не исчезает, а переносится в уже существующий endpoint:

`GET /v1/models/{model_slug}/status`

Именно его должны использовать:
- frontend UI;
- playground UI;
- любые кастомные клиенты, которым нужен preflight статус.

## UI / playground implication

Если наш UI хочет показывать пользователю:
- model is cold
- warming up
- throttled

он должен сам вызывать `/v1/models/{slug}/status` до запуска чата или в фоне, а не получать это через stream `/v1/chat/completions`.

## Files to change

- `backend/app/services/proxy_service.py`
- `backend/app/routers/playground.py` (если там есть логика, завязанная на `object: status`)
- `backend/tests/test_chat.py`
- возможно frontend playground code, если он сейчас ожидает stream-status objects

## Streaming behavior design

### Remove from OpenAI stream
Из `proxy_chat_completion_stream()` убрать:
- preflight status event before first chunk;
- `__STATUS:` markers from `stream_inference()` mapped to `object: status`;
- synthetic `ready` event.

### Keep in OpenAI stream
Оставить только OpenAI-compatible chunks:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion.chunk",
  "created": 123,
  "model": "...",
  "choices": [
    {
      "index": 0,
      "delta": {"role": "assistant"},
      "finish_reason": null
    }
  ]
}
```

и далее content/tool-call deltas, затем финальный chunk и `[DONE]`.

## Backward-compatibility decision

Мы **сознательно ломаем** старое кастомное поведение stream-status events в `/v1/chat/completions`, потому что оно нарушает заявленную OpenAI compatibility.

Это допустимо, потому что:
- для статуса уже есть отдельный dedicated endpoint;
- внешний OpenAI-compatible ecosystem важнее кастомного stream UX внутри одного endpoint.

## Testing strategy

1. Streaming test на `/v1/chat/completions`:
   - убедиться, что все SSE events имеют OpenAI-compatible shape;
   - проверить, что в stream нет `object: status`.
2. Regression test на `/v1/models/{slug}/status`:
   - endpoint всё ещё отдаёт cold/warming/throttled info.
3. Playground flow:
   - если UI зависит от status events в stream, обновить его на preflight polling через status endpoint.
4. Real-client validation:
   - `opencode` больше не должен падать на `Type validation failed` при получении stream chunks.

## Success criteria

После изменения:
- `opencode` и другие strict OpenAI clients не падают на stream parsing;
- `/v1/chat/completions` не содержит ни одного non-OpenAI SSE event;
- статус worker по-прежнему доступен через `/v1/models/{slug}/status`.

## Out of scope

- изменение non-streaming response shape;
- redesign status endpoint;
- keep-warm policy;
- model behavior / prompt tuning;
- parser/model-family tuning.
