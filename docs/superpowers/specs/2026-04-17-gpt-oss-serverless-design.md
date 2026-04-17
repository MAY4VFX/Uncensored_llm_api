# GPT-OSS serverless endpoint — дизайн

## Контекст

Нужно починить deploy path для GPT-OSS моделей в текущем serverless endpoint flow.

Во время живой диагностики были подтверждены два независимых root cause:

1. Текущий GPT-OSS image `vllm/vllm-openai:gptoss` несовместим с нашим runtime shape для function calling.
   При one-off pod запуске с:
   - `--tool-call-parser openai`
   - `--enable-auto-tool-choice`

   runtime падал сразу с ошибкой вида:
   - `invalid tool call parser: openai`

   Это означает, что проблема была не в самом parser mapping для модели, а в выбранном image/runtime.

2. После перехода на `vllm/vllm-openai:v0.11.2` parser-проблема ушла, но `ArliAI/gpt-oss-120b-Derestricted` на single-GPU H200 падал по `CUDA out of memory`.

3. После запуска на `2 GPU + tensor-parallel-size 2` модель уходит заметно дальше по startup path:
   - parser `openai` принимается
   - reasoning parser `openai_gptoss` подхватывается
   - TP=2 инициализируется корректно
   - оба worker-процесса начинают `Loading weights on cuda ...`

Это означает, что для GPT-OSS 120B текущий generic single-GPU path недостаточен.

## Цель

Сделать так, чтобы текущий serverless deploy path для GPT-OSS:
- использовал совместимый vLLM image;
- не ломался на parser mismatch;
- не пытался запускать 120B через single-GPU shape;
- прокидывал GPT-OSS через явный runtime shape, совместимый с найденными фактами диагностики.

## Что именно чиним

Чиним только GPT-OSS family deploy path в backend/scout/serverless orchestration.

В scope входят:
- family profile для GPT-OSS;
- выбор image;
- выбор `gpu_count`;
- выбор `tensor_parallel_size`;
- специальные runtime args / env для GPT-OSS serverless endpoint;
- сохранение совместимости admin/scout deploy flow с этим профилем.

В scope **не** входят:
- новый UI;
- отдельный diagnostic pod workflow как продуктовая фича;
- полный redesign RunPod orchestration;
- SSH/debug tooling;
- гарантированное устранение всех cold-start проблем RunPod serverless.

## Источники истины в коде

Точки, которые должны остаться согласованными:

- `backend/app/services/deploy_profile_service.py`
  - отвечает за family detection и итоговый deploy profile
- `backend/app/services/runpod_service.py`
  - собирает RunPod template/env/serverless endpoint
- `backend/app/routers/admin.py`
  - берёт profile и вызывает `create_endpoint(...)`
- `scout/scout/deployer.py`
  - отдельный deploy path, который не должен расходиться по GPT-OSS runtime assumptions

## Подходы

### Подход 1 — минимальный image swap

Только заменить GPT-OSS image на совместимый release image и больше ничего не менять.

#### Плюсы
- маленький diff;
- быстрое внедрение.

#### Минусы
- не решает 120B single-GPU OOM;
- не закрепляет GPT-OSS-specific runtime shape;
- оставляет слишком много implicit assumptions в generic env-only path.

### Подход 2 — рекомендованный: GPT-OSS-specific serverless profile

Для GPT-OSS сделать отдельный serverless runtime shape, но в пределах текущей архитектуры deploy profile + create_endpoint.

#### Плюсы
- закрывает оба подтверждённых root cause;
- остаётся в текущей архитектуре;
- не требует продуктового redesign;
- позволяет отдельно вести 20B и 120B.

#### Минусы
- требует special-case логики в profile/runtime builder;
- diff больше, чем у простого image swap.

### Подход 3 — полный redesign GPT-OSS orchestration

Отдельная GPT-OSS pipeline-система, special handling для cold start, engine startup и runtime introspection.

#### Плюсы
- максимальная управляемость.

#### Минусы
- избыточно для текущей задачи;
- слишком большой scope.

## Рекомендуемое решение

Берём **подход 2**.

То есть:
- GPT-OSS остаётся на `tool_parser=openai`;
- GPT-OSS уходит на `vllm/vllm-openai:v0.11.2`;
- `20b` остаётся single-GPU;
- `120b` идёт через `2 GPU + TP=2`;
- runtime shape для GPT-OSS задаётся явно, а не через слишком generic env-only assumptions.

## Дизайн профиля GPT-OSS

### Family-level defaults

Для `gpt_oss` family:
- `tool_parser = openai`
- `docker_image = vllm/vllm-openai:v0.11.2`
- `generation_config_mode = vllm`
- `default_temperature = 0.2`
- practical/native context остаются `128000`

### Разделение 20B vs 120B

Нужно различать GPT-OSS размер/класс модели внутри family.

#### GPT-OSS 20B class
Примеры:
- `openai/gpt-oss-20b`
- форки/derivatives на базе `gpt-oss-20b`

Runtime shape:
- `gpu_count = 1`
- `tensor_parallel_size = 1`

#### GPT-OSS 120B class
Примеры:
- `openai/gpt-oss-120b`
- `ArliAI/gpt-oss-120b-Derestricted`
- другие derivatives на базе `gpt-oss-120b`

Runtime shape:
- `gpu_count = 2`
- `tensor_parallel_size = 2`

### Как определить 20B vs 120B

Использовать уже доступные metadata-сигналы, в таком порядке:
1. `metadata.id`
2. `cardData.base_model`
3. `base_model:*` tags
4. fallback на `params_b`

Правило:
- если repo/base model указывает на `gpt-oss-120b` или `params_b >= 100`, это 120B class;
- если repo/base model указывает на `gpt-oss-20b` или `params_b < 100`, это 20B class.

## Дизайн runtime shape

### Почему generic env-only path недостаточен

Текущий `create_endpoint(...)` для обычного vLLM path опирается в основном на env variables:
- `MODEL_NAME`
- `MAX_MODEL_LEN`
- `TOOL_CALL_PARSER`
- `ENABLE_AUTO_TOOL_CHOICE`
- и т.д.

Для GPT-OSS этого недостаточно, потому что для 120B нам нужен не только другой image, но и явный control над runtime shape:
- `tensor_parallel_size`
- startup memory posture
- GPT-OSS-specific boot assumptions

### Что должно стать явным для GPT-OSS

Для GPT-OSS runtime builder должен уметь задавать explicit serve args, эквивалентные живой диагностике:
- `--model <repo>`
- `--max-model-len 128000`
- `--tool-call-parser openai`
- `--enable-auto-tool-choice`
- `--tensor-parallel-size 1|2`
- conservative startup tuning вроде `--max-num-batched-tokens 1024`

При этом общий deploy path не должен ломаться для остальных семейств.

### Способ внедрения

Рекомендуется не вшивать GPT-OSS special-case прямо в `admin.py` или `scout/deployer.py`.

Вместо этого:
- `resolve_deploy_profile(...)` должен возвращать расширенный runtime profile;
- `create_endpoint(...)` должен принимать эти runtime hints и собирать serverless template accordingly.

Иначе логика опять разъедется между backend/scout.

## Предлагаемая форма deploy profile

Помимо текущих полей, GPT-OSS profile должен концептуально включать:
- `gpu_type`
- `gpu_count`
- `target_context`
- `tool_parser`
- `docker_image`
- `generation_config_mode`
- `default_temperature`
- `runtime_args` или эквивалентное поле для special-case serve args

Для GPT-OSS 120B `runtime_args` должны содержать минимум:
- model
- max model len
- tool parser
- auto tool choice
- tensor parallel size 2
- max num batched tokens 1024

Для GPT-OSS 20B то же, но с `tensor_parallel_size 1`.

## Изменения в create_endpoint

`create_endpoint(...)` должен уметь:
- для обычных моделей продолжать строить generic vLLM template как сейчас;
- для GPT-OSS использовать совместимый image и explicit runtime shape.

Это можно реализовать как special-case ветку по family/model class, но желательно через уже посчитанный profile, а не повторное ad-hoc распознавание прямо в runtime builder.

## Admin / Scout поведение

### Admin

`admin.py` не должен знать GPT-OSS детали, кроме использования profile.

То есть после изменений он по-прежнему делает:
- `resolve_deploy_profile(...)`
- `create_endpoint(...)`

Но получает уже правильные:
- image
- gpu_count
- runtime shape

### Scout

`scout/scout/deployer.py` сейчас использует отдельную, более старую логику deploy shape.

Для GPT-OSS это опасно, потому что может снова создать рассинхрон между:
- backend deploy path
- scout deploy path

Поэтому GPT-OSS assumptions должны быть приведены к одному source of truth.

Минимально допустимо:
- либо подтянуть scout к той же логике выбора image/parser/runtime shape;
- либо явно запретить scout использовать старый GPT-OSS path, если он не поддерживает обновлённый runtime shape.

## Проверка корректности после внедрения

После изменения serverless path должны выполняться следующие проверки.

### Профиль
- GPT-OSS 20B → `gpu_count=1`, `tp=1`, image `v0.11.2`, parser `openai`
- GPT-OSS 120B → `gpu_count=2`, `tp=2`, image `v0.11.2`, parser `openai`

### Template/env/runtime
- serverless endpoint собирается с GPT-OSS-compatible runtime shape
- 120B path не пытается стартовать как single-GPU generic vLLM

### Живая проверка
Минимум для 120B:
- endpoint создаётся
- worker доходит дальше parser phase
- отсутствует `invalid tool call parser: openai`
- отсутствует single-GPU OOM на startup path
- worker доходит хотя бы до model load / engine init существенно дальше, чем старый path

Идеально:
- `/v1/models` отвечает
- минимальный `chat/completions` проходит

## Тестовая стратегия

Нужно обновить unit-тесты на profile/runtime assumptions.

Минимум:
- `backend/tests/test_deploy_profile_service.py`
  - проверить image `v0.11.2`
  - проверить разделение 20B и 120B по `gpu_count`
- `backend/tests/test_chat.py`
  - ожидания по image
  - ожидания по `tool_parser`
  - ожидания по `gpu_count`
  - ожидания по GPT-OSS runtime shape, если он отражается в template query / args

Важно: тесты не должны продолжать фиксировать старую ложную предпосылку, что весь GPT-OSS family идёт single-GPU generic path.

## Ограничения

Этот change **не обещает**, что RunPod serverless cold starts для GPT-OSS всегда будут идеальны.

Он решает только уже подтверждённые ошибки deploy shape:
- неверный/несовместимый image
- неверный startup shape для 120B
- отсутствие GPT-OSS-specific runtime assumptions

Если после этого останутся проблемы именно уровня RunPod worker lifecycle или long cold starts, это уже отдельная итерация.

## Итог

Чтобы endpoint для GPT-OSS реально заработал, текущий serverless path должен перестать считать GPT-OSS обычной single-GPU vLLM моделью.

Правильный shape сейчас такой:
- parser: `openai`
- image: `vllm/vllm-openai:v0.11.2`
- `20b` → `1 GPU / TP1`
- `120b` → `2 GPU / TP2`
- GPT-OSS-specific runtime args должны задаваться явно и централизованно через deploy profile + endpoint builder
