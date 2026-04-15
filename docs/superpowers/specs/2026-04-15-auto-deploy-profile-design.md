# Auto Deploy Profile Design

## Goal

Сделать так, чтобы новые модели, добавленные через UI/`add-from-hf`, автоматически получали правильный deploy-конфиг без ручной доводки:
- подходящий GPU tier;
- максимально возможный безопасный контекст;
- правильный parser/tooling режим;
- корректные vLLM/llama.cpp env flags;
- разумные sampling defaults для agent/coder моделей.

## Chosen approach

Добавляем единый backend-резолвер deploy-профиля:

`resolve_deploy_profile(hf_metadata, model_record)`

Он будет использовать:
1. family-specific rules (Qwen3-Coder, Qwen3 general, GLM, DeepSeek, GGUF, fallback)
2. общий VRAM/context калькулятор
3. явные deploy defaults для parser / generation policy / thinking mode / image choice

Именно этот резолвер становится единственным источником истины для:
- `POST /admin/models/add-from-hf`
- `POST /admin/models/{id}/deploy`
- `POST /admin/models/{id}/redeploy`

## Core idea

Текущий код выбирает GPU почти только по весам модели (`params_b × quant`).
Этого недостаточно, потому что реальный deploy зависит ещё и от:
- native/safe context length;
- KV cache budget;
- model family (coder vs chat vs gguf);
- parser requirements;
- vLLM generation behavior.

Новый flow должен считать не «какая карта влезет по весам», а:

**какой deploy profile нужен этой модели, чтобы она работала максимально хорошо автоматически**.

## Deploy profile fields

Резолвер должен возвращать структуру вроде:

```python
{
  "gpu_type": "H200_141GB",
  "gpu_count": 1,
  "target_context": 204800,
  "docker_image": "runpod/worker-v1-vllm:v...",
  "tool_parser": "qwen3_xml",
  "env_vars": [...],
  "default_temperature": 0.2,
  "thinking_mode": True,
  "generation_config_mode": "vllm",
}
```

## Family detection

Определение family должно идти по нескольким сигналам сразу:
- `hf_repo`
- `tags`
- `cardData.base_model`
- `config.json`/архитектура, если доступно
- наличие `gguf`

### Initial families

1. **Qwen3-Coder**
   - признаки: `coder` в repo/base_model/tags, `qwen3_*`, `qwen3_moe`
   - target: agent/coder profile

2. **Qwen3 general**
   - qwen3 без coder
   - target: general chat profile

3. **GLM**
   - glm family
   - свой parser/profile

4. **DeepSeek**
   - deepseek family
   - свой parser/profile

5. **GGUF**
   - `gguf` в tags/files
   - llama.cpp path

6. **Fallback**
   - безопасные дефолты

## Context policy

Для каждой family задаётся:
- `native_context`
- `practical_cap`
- формула safe target context

### Rule

Target context = минимум из:
1. family native/practical cap
2. VRAM-safe limit для выбранного GPU
3. platform cap (например 204800 / 262144 / etc)

### Important principle

Не хардкодить «всем H200 + 250K».
Нужно выбирать **максимальный безопасный контекст для конкретной модели на конкретном GPU tier**, а затем подобрать минимальный GPU, который этот контекст тянет.

## GPU selection policy

Новый селектор должен считать:
- model weights budget;
- KV cache budget под target context;
- runtime overhead;
- fallback pool chain;
- при необходимости `gpu_count > 1`.

### Rule

Выбираем **самый дешёвый GPU tier / gpu_count**, который удовлетворяет target context policy.

То есть выбор идёт не от весов модели, а от:

`weights + KV(context) + overhead`.

## Parser / runtime policy

### Qwen3-Coder family
- не использовать generic `hermes` по умолчанию, если family-aware parser доступен;
- parser должен быть configurable per-family (и позже per-model override);
- generation config mode: `vllm`;
- low temperature defaults for agentic use.

### GGUF
- использовать llama.cpp image/path;
- контекст и args через `LLAMA_SERVER_CMD_ARGS`.

### Fallback
- conservative parser + conservative context.

## Sampling defaults

Для agent/coder families по умолчанию:
- deterministic / low-stochasticity profile;
- `generation_config=vllm`;
- lower default temperature.

Для general chat family можно оставить более мягкие defaults.

## Persistence

Часть auto profile должна сохраняться в БД как computed defaults, чтобы UI сразу показывал правильные значения.

Минимальный набор сохраняемых полей:
- `gpu_type`
- `gpu_count`
- `max_context_length`

Следующим этапом можно добавить per-model override fields для:
- `tool_parser`
- `default_temperature`
- `thinking_mode`

Но это не обязательно для первого шага, если резолвер пока выдаёт это только в deploy-time env.

## Integration points

### 1. add-from-hf
При добавлении модели:
- fetch HF metadata
- вызвать `resolve_deploy_profile(...)`
- сохранить computed defaults в модель

### 2. deploy / redeploy
При deploy и redeploy:
- не собирать env ad-hoc из хардкода
- сначала вызвать `resolve_deploy_profile(...)`
- потом использовать его `gpu_type`, `gpu_count`, `target_context`, parser/env vars/image

## Non-goals

Сразу не делаем:
- полную UI-форму для ручного выбора parser/sampling profile;
- dynamic benchmarking before deploy;
- cross-model eval runner;
- zero-downtime dual-endpoint switchover.

## Files likely to change

- `backend/app/routers/admin.py`
- `backend/app/services/runpod_service.py`
- возможно новый helper/module, например `backend/app/services/deploy_profile_service.py`
- `scout/scout/gpu_selector.py`
- возможно `backend/app/models/llm_model.py` / schemas, если добавим per-model override fields позже

## Testing strategy

1. Unit tests for family detection
2. Unit tests for GPU/context calculation
3. Regression tests for known model repos:
   - DavidAU current model
   - Huihui Qwen3-Coder-30B-A3B
   - GGUF repo
4. End-to-end test:
   - `add-from-hf` creates expected defaults
   - `deploy` uses resolved profile

## Success criteria

Если пользователь добавляет через UI новую coder/agent-модель, то без ручной правки backend должен:
- не выбрать заведомо слабый GPU tier вроде A100, если target context требует H200;
- не выставить контекст слишком низко или слишком агрессивно;
- не поставить неподходящий parser по умолчанию;
- использовать agent-friendly sampling defaults.
