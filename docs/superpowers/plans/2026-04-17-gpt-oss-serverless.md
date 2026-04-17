# GPT-OSS Serverless Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Починить serverless deploy path для GPT-OSS так, чтобы parser mismatch исчез, `20b` и `120b` получали корректный runtime shape, а `120b` больше не стартовал как single-GPU endpoint.

**Architecture:** Сфокусировать GPT-OSS runtime assumptions в одном source of truth: backend deploy profile должен различать `20b` и `120b`, возвращать совместимый image и runtime hints, а serverless endpoint builder должен превращать эти hints в явный GPT-OSS runtime shape. Admin router и scout должны лишь потреблять этот профиль, не дублируя GPT-OSS-специфику.

**Tech Stack:** FastAPI, async SQLAlchemy, pytest, RunPod GraphQL template/endpoint creation, vLLM serverless worker runtime, scout GPU selector helpers.

---

## File Structure

- **Modify:** `backend/app/services/deploy_profile_service.py`
  - Научить GPT-OSS profile различать `20b` vs `120b`
  - Возвращать `gpu_count`, `docker_image` и GPT-OSS runtime hints в одном профиле
- **Modify:** `backend/app/services/runpod_service.py`
  - Собрать GPT-OSS-specific runtime shape для serverless template
  - Не ломать generic path для остальных семейств
- **Modify:** `backend/tests/test_deploy_profile_service.py`
  - Зафиксировать новые profile assumptions для GPT-OSS `20b` и `120b`
- **Modify:** `backend/tests/test_chat.py`
  - Зафиксировать новые ожидания по image, `gpu_count` и template query/runtime shape
- **Modify:** `scout/scout/gpu_selector.py`
  - Свести GPT-OSS image/parser/profile assumptions к актуальному runtime
- **Modify:** `scout/tests/test_gpt_oss_support.py`
  - Зафиксировать новый GPT-OSS image и profile behavior в scout path

---

### Task 1: Зафиксировать failing tests для GPT-OSS profile split

**Files:**
- Modify: `backend/tests/test_deploy_profile_service.py`
- Test: `backend/tests/test_deploy_profile_service.py`

- [ ] **Step 1: Add a failing test for GPT-OSS 120B requiring 2 GPUs**

Add this test to `backend/tests/test_deploy_profile_service.py` after the existing GPT-OSS tests:

```python
def test_gpt_oss_120b_uses_two_gpu_runtime_shape():
    metadata = {
        "id": "ArliAI/gpt-oss-120b-Derestricted",
        "tags": [
            "gpt_oss",
            "reasoning",
            "base_model:openai/gpt-oss-120b",
        ],
        "cardData": {"base_model": ["openai/gpt-oss-120b"]},
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=117.0, quantization="FP16")

    assert profile["family"] == "gpt_oss"
    assert profile["tool_parser"] == "openai"
    assert profile["docker_image"] == "vllm/vllm-openai:v0.11.2"
    assert profile["gpu_type"] == "H200_141GB"
    assert profile["gpu_count"] == 2
    assert profile["runtime_args"]["tensor_parallel_size"] == 2
    assert profile["runtime_args"]["max_num_batched_tokens"] == 1024
```

- [ ] **Step 2: Add a failing test for GPT-OSS 20B staying single-GPU**

Add this second test to `backend/tests/test_deploy_profile_service.py`:

```python
def test_gpt_oss_20b_stays_single_gpu_runtime_shape():
    metadata = {
        "id": "openai/gpt-oss-20b",
        "tags": ["gpt_oss"],
        "cardData": {"base_model": ["openai/gpt-oss-20b"]},
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=20.0, quantization="Q8")

    assert profile["family"] == "gpt_oss"
    assert profile["tool_parser"] == "openai"
    assert profile["docker_image"] == "vllm/vllm-openai:v0.11.2"
    assert profile["gpu_type"] == "H200_141GB"
    assert profile["gpu_count"] == 1
    assert profile["runtime_args"]["tensor_parallel_size"] == 1
    assert profile["runtime_args"]["max_num_batched_tokens"] == 1024
```

- [ ] **Step 3: Run only the new profile tests and verify they fail**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_deploy_profile_service.py -k "gpt_oss_120b_uses_two_gpu_runtime_shape or gpt_oss_20b_stays_single_gpu_runtime_shape" -v
```
Expected: FAIL because `gpu_count` is still `1` for 120B and `runtime_args` does not yet exist in the profile.

- [ ] **Step 4: Commit the failing backend profile tests**

```bash
git add backend/tests/test_deploy_profile_service.py
git commit -m "test: add failing GPT-OSS runtime profile coverage"
```

---

### Task 2: Сделать GPT-OSS profile aware of 20B vs 120B

**Files:**
- Modify: `backend/app/services/deploy_profile_service.py`
- Test: `backend/tests/test_deploy_profile_service.py`

- [ ] **Step 1: Add a helper that classifies GPT-OSS model size class**

Add this helper near `_detect_family()` in `backend/app/services/deploy_profile_service.py`:

```python
def _detect_gpt_oss_size_class(metadata: dict, params_b: float) -> str:
    repo = (metadata.get("id") or "").lower()
    card = metadata.get("cardData") or {}
    base_model = card.get("base_model") or []
    if isinstance(base_model, str):
        base_model = [base_model]
    tags = [str(t).lower() for t in metadata.get("tags", [])]
    base_text = " ".join(
        [
            *(str(item).lower() for item in base_model),
            *(tag.split(":", 1)[1] for tag in tags if tag.startswith("base_model:")),
        ]
    )

    if "gpt-oss-120b" in repo or "gpt-oss-120b" in base_text or params_b >= 100:
        return "120b"
    return "20b"
```

- [ ] **Step 2: Extend the GPT-OSS profile to include runtime args**

Change the GPT-OSS entry in `FAMILY_LIMITS` from:

```python
    "gpt_oss": {
        "native_context": 128000,
        "practical_cap": 128000,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "openai",
        "docker_image": "vllm/vllm-openai:v0.11.2",
        "default_temperature": 0.2,
    },
```

to:

```python
    "gpt_oss": {
        "native_context": 128000,
        "practical_cap": 128000,
        "preferred_gpu": "H200_141GB",
        "tool_parser": "openai",
        "docker_image": "vllm/vllm-openai:v0.11.2",
        "default_temperature": 0.2,
        "runtime_args": {
            "max_num_batched_tokens": 1024,
        },
    },
```

- [ ] **Step 3: Override GPT-OSS gpu_count and TP in resolve_deploy_profile()**

Replace the end of `resolve_deploy_profile()` in `backend/app/services/deploy_profile_service.py` with this shape:

```python
def resolve_deploy_profile(metadata: dict, params_b: float, quantization: str) -> dict:
    family = _detect_family(metadata)
    limits = FAMILY_LIMITS[family]
    desired_context = limits["practical_cap"]
    gpu_type, gpu_count = _select_gpu_for_context(params_b, quantization, desired_context, family)
    safe_context = _safe_context_on_gpu(params_b, quantization, gpu_type, family)
    safe_context = _coerce_minimum_context(family, gpu_type, safe_context)
    target_context = min(desired_context, limits["native_context"], safe_context)

    docker_image = limits.get("docker_image", "")
    if not docker_image and family == "gguf":
        docker_image = "may4vfx/worker-llamacpp:latest"

    runtime_args = dict(limits.get("runtime_args", {}))

    if family == "gpt_oss":
        size_class = _detect_gpt_oss_size_class(metadata, params_b)
        if size_class == "120b":
            gpu_count = 2
            runtime_args["tensor_parallel_size"] = 2
        else:
            gpu_count = 1
            runtime_args["tensor_parallel_size"] = 1

    return {
        "family": family,
        "gpu_type": gpu_type,
        "gpu_count": gpu_count,
        "target_context": target_context,
        "tool_parser": limits["tool_parser"],
        "docker_image": docker_image,
        "default_temperature": limits["default_temperature"],
        "generation_config_mode": "vllm",
        "enable_prefix_caching": True,
        "enable_chunked_prefill": True,
        "runtime_args": runtime_args,
    }
```

- [ ] **Step 4: Run the focused backend profile tests and verify they pass**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_deploy_profile_service.py -k gpt_oss -v
```
Expected: PASS for old GPT-OSS detection tests plus the new 20B/120B runtime shape tests.

- [ ] **Step 5: Commit the profile implementation**

```bash
git add backend/app/services/deploy_profile_service.py backend/tests/test_deploy_profile_service.py
git commit -m "feat: split GPT-OSS serverless profile by model size"
```

---

### Task 3: Зафиксировать failing tests для GPT-OSS endpoint builder runtime shape

**Files:**
- Modify: `backend/tests/test_chat.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Add a failing test for 120B endpoint creation using 2 GPUs and TP=2**

Append this test near the existing `test_create_endpoint_uses_openai_parser_and_larger_disk_for_gpt_oss` in `backend/tests/test_chat.py`:

```python
@pytest.mark.asyncio
async def test_create_endpoint_uses_tp2_shape_for_gpt_oss_120b(monkeypatch):
    from app.services import runpod_service

    captured_queries = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            if len(captured_queries) == 1:
                return {"data": {"saveTemplate": {"id": "tpl-1", "name": "tpl"}}}
            return {"data": {"saveEndpoint": {"id": "ep-1", "name": "ep", "gpuIds": "HOPPER_141", "templateId": "tpl-1"}}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            captured_queries.append(json["query"])
            return FakeResponse()

    monkeypatch.setattr(runpod_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await runpod_service.create_endpoint(
        name="unch-gpt-oss-120b",
        gpu_type="H200_141GB",
        docker_image="vllm/vllm-openai:v0.11.2",
        model_name="ArliAI/gpt-oss-120b-Derestricted",
        params_b=117.0,
        max_model_len=128000,
        gpu_count=2,
        tool_parser="openai",
        generation_config_mode="vllm",
        default_temperature=0.2,
        runtime_args={
            "tensor_parallel_size": 2,
            "max_num_batched_tokens": 1024,
        },
    )

    assert result["data"]["saveEndpoint"]["id"] == "ep-1"
    template_query = captured_queries[0]
    endpoint_query = captured_queries[1]
    assert 'imageName: "vllm/vllm-openai:v0.11.2"' in template_query
    assert 'TOOL_CALL_PARSER", value: "openai"' in template_query
    assert 'gpuCount: 2' in endpoint_query
    assert '--tensor-parallel-size 2' in template_query
    assert '--max-num-batched-tokens 1024' in template_query
```

- [ ] **Step 2: Add a failing test for 20B staying on 1 GPU and TP=1**

Add this second test to `backend/tests/test_chat.py`:

```python
@pytest.mark.asyncio
async def test_create_endpoint_uses_tp1_shape_for_gpt_oss_20b(monkeypatch):
    from app.services import runpod_service

    captured_queries = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            if len(captured_queries) == 1:
                return {"data": {"saveTemplate": {"id": "tpl-1", "name": "tpl"}}}
            return {"data": {"saveEndpoint": {"id": "ep-1", "name": "ep", "gpuIds": "HOPPER_141", "templateId": "tpl-1"}}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            captured_queries.append(json["query"])
            return FakeResponse()

    monkeypatch.setattr(runpod_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await runpod_service.create_endpoint(
        name="unch-gpt-oss-20b",
        gpu_type="H200_141GB",
        docker_image="vllm/vllm-openai:v0.11.2",
        model_name="openai/gpt-oss-20b",
        params_b=20.0,
        max_model_len=128000,
        gpu_count=1,
        tool_parser="openai",
        generation_config_mode="vllm",
        default_temperature=0.2,
        runtime_args={
            "tensor_parallel_size": 1,
            "max_num_batched_tokens": 1024,
        },
    )

    assert result["data"]["saveEndpoint"]["id"] == "ep-1"
    template_query = captured_queries[0]
    endpoint_query = captured_queries[1]
    assert '--tensor-parallel-size 1' in template_query
    assert '--max-num-batched-tokens 1024' in template_query
    assert 'gpuCount: 2' not in endpoint_query
```

- [ ] **Step 3: Run the new endpoint-builder tests to verify they fail**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k "tp2_shape_for_gpt_oss_120b or tp1_shape_for_gpt_oss_20b" -v
```
Expected: FAIL because `create_endpoint()` does not yet accept `runtime_args` and does not emit GPT-OSS explicit startup args.

- [ ] **Step 4: Commit the failing endpoint-builder tests**

```bash
git add backend/tests/test_chat.py
git commit -m "test: add failing GPT-OSS endpoint runtime shape coverage"
```

---

### Task 4: Сделать GPT-OSS explicit runtime shape в create_endpoint()

**Files:**
- Modify: `backend/app/services/runpod_service.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Extend create_endpoint() signature with runtime_args**

Change the function signature in `backend/app/services/runpod_service.py` from:

```python
async def create_endpoint(
    name: str,
    gpu_type: str,
    docker_image: str = "",
    model_name: str = "",
    max_workers: int = 1,
    idle_timeout: int = 30,
    params_b: float = 0,
    max_model_len: int = 4096,
    gpu_count: int = 1,
    tool_parser: str | None = None,
    generation_config_mode: str | None = None,
    default_temperature: float | None = None,
    db=None,
) -> dict:
```

to:

```python
async def create_endpoint(
    name: str,
    gpu_type: str,
    docker_image: str = "",
    model_name: str = "",
    max_workers: int = 1,
    idle_timeout: int = 30,
    params_b: float = 0,
    max_model_len: int = 4096,
    gpu_count: int = 1,
    tool_parser: str | None = None,
    generation_config_mode: str | None = None,
    default_temperature: float | None = None,
    runtime_args: dict | None = None,
    db=None,
) -> dict:
```

- [ ] **Step 2: Add a GPT-OSS dockerArgs builder**

Insert this helper near `GPT_OSS_IMAGE` in `backend/app/services/runpod_service.py`:

```python
def _build_gpt_oss_docker_args(
    model_name: str,
    max_model_len: int,
    tool_parser: str | None,
    runtime_args: dict | None,
) -> str:
    runtime_args = runtime_args or {}
    tensor_parallel_size = runtime_args.get("tensor_parallel_size", 1)
    max_num_batched_tokens = runtime_args.get("max_num_batched_tokens", 1024)
    parser = tool_parser or "openai"

    return " ".join(
        [
            f"--model {model_name}",
            "--host 0.0.0.0",
            "--port 8000",
            f"--max-model-len {max_model_len}",
            f"--tool-call-parser {parser}",
            "--enable-auto-tool-choice",
            f"--tensor-parallel-size {tensor_parallel_size}",
            f"--max-num-batched-tokens {max_num_batched_tokens}",
        ]
    )
```

- [ ] **Step 3: Use dockerArgs for GPT-OSS template creation**

In the template query builder inside `create_endpoint()`, replace the hardcoded:

```python
f' dockerArgs: "",'
```

with logic like:

```python
        docker_args = ""
        if "gpt-oss" in model_name.lower():
            docker_args = _build_gpt_oss_docker_args(
                model_name=model_name,
                max_model_len=max_model_len,
                tool_parser=tool_parser,
                runtime_args=runtime_args,
            )
```

and then use it in the template mutation:

```python
        tmpl_query = (
            f'mutation {{ saveTemplate(input: {{'
            f' name: "{tmpl_name}",'
            f' imageName: "{docker_image}",'
            f' dockerArgs: "{docker_args.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}",'
            f' containerDiskInGb: {container_disk},'
            f' volumeInGb: 0,'
            f' isServerless: true,'
            f' env: [{env_str}]'
            f' }}) {{ id name }} }}'
        )
```

- [ ] **Step 4: Pass through GPT-OSS runtime env without breaking other models**

Keep the existing env variables for GPT-OSS, but do not remove:
- `MODEL_NAME`
- `MAX_MODEL_LEN`
- `TOOL_CALL_PARSER`
- `ENABLE_AUTO_TOOL_CHOICE`

The point is to add explicit startup args for GPT-OSS, not to invent a brand-new deploy transport.

- [ ] **Step 5: Run the GPT-OSS endpoint-builder tests and verify they pass**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k "gpt_oss" -v
```
Expected: PASS for the GPT-OSS deploy/redeploy tests and the new explicit runtime-shape tests.

- [ ] **Step 6: Commit the endpoint builder changes**

```bash
git add backend/app/services/runpod_service.py backend/tests/test_chat.py
git commit -m "feat: add explicit GPT-OSS serverless runtime shape"
```

---

### Task 5: Прокинуть runtime_args из profile в admin deploy path

**Files:**
- Modify: `backend/app/routers/admin.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Extend the existing redeploy/deploy tests to assert runtime_args**

In `backend/tests/test_chat.py`, update the successful GPT-OSS redeploy test assertions to include:

```python
    assert kwargs["gpu_count"] == 2
    assert kwargs["runtime_args"]["tensor_parallel_size"] == 2
    assert kwargs["runtime_args"]["max_num_batched_tokens"] == 1024
```

Also add a focused assertion in the `add_from_hf` path by checking the response body or profile-driven values if the route exposes them indirectly.

- [ ] **Step 2: Run the updated admin-route test and verify it fails**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k "redeploy_uses_gpt_oss_profile" -v
```
Expected: FAIL because `runtime_args` is not yet being passed from `profile` into `create_endpoint()`.

- [ ] **Step 3: Pass runtime_args in both deploy and redeploy route handlers**

In `backend/app/routers/admin.py`, add `runtime_args=profile["runtime_args"],` to both `create_endpoint(...)` calls.

For `deploy_model()` use:

```python
        result = await create_endpoint(
            name=f"unch-{model.slug}",
            gpu_type=profile["gpu_type"],
            docker_image=profile["docker_image"],
            model_name=model.hf_repo,
            params_b=float(model.params_b or 0),
            max_model_len=profile["target_context"],
            gpu_count=profile["gpu_count"],
            tool_parser=profile["tool_parser"],
            generation_config_mode=profile["generation_config_mode"],
            default_temperature=profile["default_temperature"],
            runtime_args=profile["runtime_args"],
            db=db,
        )
```

Make the same addition in `redeploy_model()`.

- [ ] **Step 4: Run the updated admin-route tests and verify they pass**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k "redeploy_uses_gpt_oss_profile or add_model_from_hf_uses_gpt_oss_profile" -v
```
Expected: PASS.

- [ ] **Step 5: Commit the router integration**

```bash
git add backend/app/routers/admin.py backend/tests/test_chat.py
git commit -m "feat: pass GPT-OSS runtime args through admin deploy flow"
```

---

### Task 6: Свести scout GPT-OSS assumptions к backend source of truth

**Files:**
- Modify: `scout/scout/gpu_selector.py`
- Modify: `scout/tests/test_gpt_oss_support.py`
- Test: `scout/tests/test_gpt_oss_support.py`

- [ ] **Step 1: Add failing scout tests for the new GPT-OSS image and 120B multi-GPU behavior**

In `scout/tests/test_gpt_oss_support.py`, replace the current dedicated-runtime-image test and add this new test block:

```python
def test_gpt_oss_uses_v0112_runtime_image():
    metadata = {
        "id": "ArliAI/Derestricted-Reasoner",
        "tags": ["reasoning", "base_model:openai/gpt-oss-120b"],
        "cardData": {"base_model": ["openai/gpt-oss-120b"]},
    }
    assert resolve_docker_image("ArliAI/gpt-oss-120b-Derestricted") == "vllm/vllm-openai:v0.11.2"
    assert resolve_docker_image(metadata) == "vllm/vllm-openai:v0.11.2"


def test_gpt_oss_120b_profile_requires_two_gpu_shape():
    gpu_type, _cost_hr, max_context = resolve_profile(
        "ArliAI/gpt-oss-120b-Derestricted",
        117.0,
        "FP16",
    )

    assert gpu_type == "H200_141GB"
    assert max_context >= 128000
    assert resolve_tool_parser("ArliAI/gpt-oss-120b-Derestricted") == "openai"
```

- [ ] **Step 2: Run scout GPT-OSS tests to verify at least the image test fails**

Run:
```bash
cd /Users/may/Uncensored_llm_api && pytest scout/tests/test_gpt_oss_support.py -v
```
Expected: FAIL because scout still returns `vllm/vllm-openai:gptoss`.

- [ ] **Step 3: Update scout runtime image mapping**

In `scout/scout/gpu_selector.py`, change:

```python
    if family == "gpt_oss":
        return "vllm/vllm-openai:gptoss"
```

to:

```python
    if family == "gpt_oss":
        return "vllm/vllm-openai:v0.11.2"
```

- [ ] **Step 4: Run scout GPT-OSS tests and verify they pass**

Run:
```bash
cd /Users/may/Uncensored_llm_api && pytest scout/tests/test_gpt_oss_support.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit the scout alignment**

```bash
git add scout/scout/gpu_selector.py scout/tests/test_gpt_oss_support.py
git commit -m "fix: align scout GPT-OSS runtime image with backend"
```

---

### Task 7: Выполнить focused regression verification

**Files:**
- Modify: none
- Test: existing backend and scout tests only

- [ ] **Step 1: Run all backend tests touched by GPT-OSS changes**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_deploy_profile_service.py tests/test_chat.py -v
```
Expected: PASS.

- [ ] **Step 2: Run scout GPT-OSS tests again in the full repo context**

Run:
```bash
cd /Users/may/Uncensored_llm_api && pytest scout/tests/test_gpt_oss_support.py -v
```
Expected: PASS.

- [ ] **Step 3: Verify no stale references to the old GPT-OSS image remain in code paths we changed**

Run:
```bash
cd /Users/may/Uncensored_llm_api && rg "vllm/vllm-openai:gptoss|tool_call_parser.*openai|runtime_args" backend scout -n
```
Expected:
- no stale runtime image references in modified GPT-OSS paths;
- `tool_parser=openai` remains present;
- new `runtime_args` references appear in backend profile/admin/runtime builder.

- [ ] **Step 4: Commit any last test-only cleanup if needed**

```bash
git add backend/tests/test_deploy_profile_service.py backend/tests/test_chat.py scout/tests/test_gpt_oss_support.py
 git commit -m "test: finalize GPT-OSS serverless regression coverage"
```

Only do this if Step 3 required any cleanup. If no cleanup was needed, skip this commit.

---

### Task 8: Verify the serverless behavior through the actual deployment path

**Files:**
- Modify: none
- Test: live deploy path only

- [ ] **Step 1: Push the branch so Dokploy/auto-deploy path can pick up the backend changes**

Run:
```bash
git status --short
git push
```
Expected:
- working tree clean except intended changes before push;
- push succeeds.

- [ ] **Step 2: Trigger a redeploy for a GPT-OSS 120B model through the actual admin path**

Use the real admin/API path already used by the product to redeploy an existing GPT-OSS 120B model.

Expected runtime characteristics after the change:
- image resolves to `vllm/vllm-openai:v0.11.2`
- endpoint is created with `gpuCount: 2`
- GPT-OSS startup uses explicit runtime args including `--tensor-parallel-size 2`

- [ ] **Step 3: Observe worker logs until parser phase is passed**

Verify that the new worker does **not** fail with:
- `invalid tool call parser: openai`

Expected: worker progresses into model loading.

- [ ] **Step 4: Observe startup until at least model-load phase**

Verify that the new worker does **not** fail with the previous single-GPU OOM pattern.

Expected: startup reaches at least weight download / shard loading / engine init further than before.

- [ ] **Step 5: If the endpoint reaches ready-state, test `/v1/models` and one minimal request**

Run equivalent API checks against the real endpoint:
- `GET /v1/models`
- one minimal non-stream `chat/completions`

Expected:
- `/v1/models` responds successfully
- minimal request returns a valid response

- [ ] **Step 6: Commit nothing here**

This task is verification only. No code changes. No commit.

---

## Spec Coverage Check

- **Image mismatch fixed:** covered by Tasks 2, 4, 6, 8.
- **120B single-GPU shape fixed:** covered by Tasks 2, 4, 5, 8.
- **20B vs 120B split:** covered by Tasks 1, 2, 3.
- **Explicit GPT-OSS runtime args:** covered by Tasks 3 and 4.
- **Admin path consumes unified profile:** covered by Task 5.
- **Scout path alignment:** covered by Task 6.
- **Regression tests:** covered by Task 7.
- **Live deployment verification:** covered by Task 8.

No spec gaps found.
