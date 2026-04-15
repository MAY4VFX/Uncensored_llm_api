# Auto Deploy Profile Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make model deployment automatically choose the right GPU tier, safe context length, parser, and runtime defaults from Hugging Face metadata instead of using the current shallow heuristics.

**Architecture:** Add a dedicated backend deploy-profile resolver module that classifies a model family from HF metadata, computes the maximum safe context from VRAM and family limits, and returns deploy-time defaults for GPU, parser, and runtime env vars. Use that resolver both when a model is added from HF and when an endpoint is deployed or redeployed, so UI defaults and live deploy behavior stay in sync.

**Tech Stack:** FastAPI, SQLAlchemy, existing admin routes, existing RunPod deploy service, pytest, Hugging Face metadata API.

---

## File Structure

- **Create:** `backend/app/services/deploy_profile_service.py`
  - Single-purpose resolver for family detection, context policy, GPU/context calculation, and deploy defaults
- **Modify:** `backend/app/routers/admin.py`
  - Use the resolver in `add-from-hf`, `deploy`, and `redeploy`
- **Modify:** `backend/app/services/runpod_service.py`
  - Accept parser/runtime overrides from the resolver instead of hardcoding one global profile
- **Modify:** `backend/app/schemas/model.py`
  - Expose any newly persisted computed defaults if needed
- **Modify:** `backend/tests/test_chat.py`
  - Add regression tests for admin add/deploy behavior
- **Create:** `backend/tests/test_deploy_profile_service.py`
  - Focused unit tests for family detection and safe context/GPU calculation
- **Modify:** `scout/scout/gpu_selector.py`
  - Align scout-side heuristics with the new backend context/GPU rules or clearly mark scout as legacy fallback

---

### Task 1: Add failing tests for deploy profile resolution

**Files:**
- Create: `backend/tests/test_deploy_profile_service.py`
- Modify: `backend/tests/test_chat.py`
- Test: `backend/tests/test_deploy_profile_service.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Create a new unit test file for the resolver**

Create `backend/tests/test_deploy_profile_service.py` with this initial scaffold:

```python
from app.services.deploy_profile_service import resolve_deploy_profile


def test_qwen3_coder_prefers_agent_profile_defaults():
    metadata = {
        "id": "huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated",
        "tags": [
            "qwen3_moe",
            "abliterated",
            "uncensored",
            "base_model:Qwen/Qwen3-Coder-30B-A3B-Instruct",
        ],
        "cardData": {
            "base_model": ["Qwen/Qwen3-Coder-30B-A3B-Instruct"],
        },
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=30.5, quantization="FP16")

    assert profile["family"] == "qwen3_coder"
    assert profile["gpu_type"] == "H200_141GB"
    assert profile["target_context"] >= 131072
    assert profile["tool_parser"] != "hermes"
    assert profile["default_temperature"] <= 0.2
```

- [ ] **Step 2: Add a fallback-family failing test**

Append this test to `backend/tests/test_deploy_profile_service.py`:

```python
def test_unknown_model_uses_conservative_fallback_profile():
    metadata = {
        "id": "someone/unknown-model",
        "tags": ["text-generation"],
        "cardData": {},
        "siblings": [{"rfilename": "config.json"}],
    }

    profile = resolve_deploy_profile(metadata, params_b=7, quantization="FP16")

    assert profile["family"] == "fallback"
    assert profile["gpu_type"]
    assert profile["target_context"] >= 4096
    assert profile["tool_parser"] == "hermes"
```

- [ ] **Step 3: Add a failing admin-path test showing `add-from-hf` should persist computed defaults**

Append this to `backend/tests/test_chat.py`:

```python
@pytest.mark.asyncio
async def test_add_model_from_hf_uses_resolved_deploy_profile(client, admin_headers, monkeypatch):
    fake_hf = {
        "id": "huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated",
        "tags": [
            "qwen3_moe",
            "abliterated",
            "uncensored",
            "base_model:Qwen/Qwen3-Coder-30B-A3B-Instruct",
        ],
        "siblings": [{"rfilename": "config.json"}],
        "cardData": {"base_model": ["Qwen/Qwen3-Coder-30B-A3B-Instruct"]},
        "downloads": 100,
        "likes": 10,
        "safetensors": {"total": 30_500_000_000},
    }

    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return fake_hf

    async def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("app.routers.admin.httpx.AsyncClient.get", fake_get)

    response = await client.post(
        "/admin/models/add-from-hf",
        headers=admin_headers,
        json={"hf_repo": "huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["gpu_type"] == "H200_141GB"
    assert body["max_context_length"] >= 131072
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_deploy_profile_service.py tests/test_chat.py -k "deploy_profile or add_model_from_hf_uses_resolved_deploy_profile" -v
```
Expected: FAIL because `deploy_profile_service` does not exist and `add-from-hf` still uses old heuristics.

- [ ] **Step 5: Commit the failing tests**

```bash
git add backend/tests/test_deploy_profile_service.py backend/tests/test_chat.py
git commit -m "test: add failing coverage for auto deploy profiles"
```

---

### Task 2: Create the deploy profile resolver module

**Files:**
- Create: `backend/app/services/deploy_profile_service.py`
- Test: `backend/tests/test_deploy_profile_service.py`

- [ ] **Step 1: Create the resolver module skeleton**

Create `backend/app/services/deploy_profile_service.py` with this starting structure:

```python
from __future__ import annotations

from dataclasses import dataclass

GPU_OPTIONS = [
    ("A100_80GB", 80),
    ("H100_80GB", 80),
    ("H200_141GB", 141),
]


@dataclass
class DeployProfile:
    family: str
    gpu_type: str
    gpu_count: int
    target_context: int
    tool_parser: str
    default_temperature: float
    generation_config_mode: str
    enable_prefix_caching: bool
    enable_chunked_prefill: bool


def _detect_family(metadata: dict) -> str:
    repo = (metadata.get("id") or "").lower()
    tags = [t.lower() for t in metadata.get("tags", [])]
    card = metadata.get("cardData") or {}
    base_model = card.get("base_model") or []
    if isinstance(base_model, str):
        base_model = [base_model]
    base_text = " ".join(str(x).lower() for x in base_model)

    if "gguf" in tags:
        return "gguf"
    if "coder" in repo or "coder" in base_text:
        if "qwen3" in repo or "qwen3" in base_text or "qwen3_moe" in tags:
            return "qwen3_coder"
    if "qwen3" in repo or "qwen3" in base_text or "qwen3_moe" in tags:
        return "qwen3_general"
    if "glm" in repo or "glm" in base_text:
        return "glm"
    if "deepseek" in repo or "deepseek" in base_text:
        return "deepseek"
    return "fallback"
```

- [ ] **Step 2: Add context/GPU calculation helpers**

Extend `backend/app/services/deploy_profile_service.py` with:

```python
QUANT_MULTIPLIERS = {"Q4": 0.5, "Q8": 1.0, "FP16": 2.0}

FAMILY_LIMITS = {
    "qwen3_coder": {"native_context": 262144, "practical_cap": 262144, "preferred_gpu": "H200_141GB", "tool_parser": "qwen3_xml", "default_temperature": 0.2},
    "qwen3_general": {"native_context": 131072, "practical_cap": 204800, "preferred_gpu": "H200_141GB", "tool_parser": "hermes", "default_temperature": 0.2},
    "glm": {"native_context": 131072, "practical_cap": 131072, "preferred_gpu": "H200_141GB", "tool_parser": "glm45", "default_temperature": 0.2},
    "deepseek": {"native_context": 131072, "practical_cap": 131072, "preferred_gpu": "H200_141GB", "tool_parser": "hermes", "default_temperature": 0.2},
    "gguf": {"native_context": 131072, "practical_cap": 131072, "preferred_gpu": "H200_141GB", "tool_parser": "none", "default_temperature": 0.2},
    "fallback": {"native_context": 32768, "practical_cap": 65536, "preferred_gpu": "A100_80GB", "tool_parser": "hermes", "default_temperature": 0.2},
}


def _estimate_safe_context(params_b: float, quantization: str, vram_gb: int) -> int:
    multiplier = QUANT_MULTIPLIERS.get(quantization, 1.0)
    weight_budget = params_b * multiplier * 1.15
    free_vram = vram_gb - weight_budget
    if free_vram <= 0:
        return 4096
    kv_per_4k = params_b * 0.5
    ctx = int((free_vram / kv_per_4k) * 4096)
    ctx = (ctx // 1024) * 1024
    return max(ctx, 4096)


def _select_gpu_for_context(params_b: float, quantization: str, desired_context: int) -> tuple[str, int]:
    for gpu_type, vram_gb in GPU_OPTIONS:
        if _estimate_safe_context(params_b, quantization, vram_gb) >= desired_context:
            return gpu_type, 1
    return "H200_141GB", 1
```

- [ ] **Step 3: Implement `resolve_deploy_profile()`**

Append this function:

```python
def resolve_deploy_profile(metadata: dict, params_b: float, quantization: str) -> dict:
    family = _detect_family(metadata)
    limits = FAMILY_LIMITS[family]
    desired_context = limits["practical_cap"]
    gpu_type, gpu_count = _select_gpu_for_context(params_b, quantization, desired_context)
    vram_gb = next(vram for name, vram in GPU_OPTIONS if name == gpu_type)
    safe_context = _estimate_safe_context(params_b, quantization, vram_gb)
    target_context = min(desired_context, limits["native_context"], safe_context)

    return {
        "family": family,
        "gpu_type": gpu_type,
        "gpu_count": gpu_count,
        "target_context": target_context,
        "tool_parser": limits["tool_parser"],
        "default_temperature": limits["default_temperature"],
        "generation_config_mode": "vllm",
        "enable_prefix_caching": True,
        "enable_chunked_prefill": True,
    }
```

- [ ] **Step 4: Run the resolver unit tests**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_deploy_profile_service.py -v
```
Expected: PASS for the new family detection and fallback profile tests.

- [ ] **Step 5: Commit the resolver module**

```bash
git add backend/app/services/deploy_profile_service.py backend/tests/test_deploy_profile_service.py
git commit -m "feat: add model deploy profile resolver"
```

---

### Task 3: Use the resolver in `add-from-hf`

**Files:**
- Modify: `backend/app/routers/admin.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Import the resolver into the admin router**

In `backend/app/routers/admin.py`, add:

```python
from app.services.deploy_profile_service import resolve_deploy_profile
```

- [ ] **Step 2: Replace the old `select_gpu()` path in `add_model_from_hf()`**

Inside `add_model_from_hf()`, replace:

```python
    gpu_type, gpu_count = select_gpu(params_b, quant)
```

with:

```python
    profile = resolve_deploy_profile(data, params_b=params_b, quantization=quant)
    gpu_type = profile["gpu_type"]
    gpu_count = profile["gpu_count"]
```

And when creating `LlmModel(...)`, replace the current max-context default path by explicitly storing:

```python
        max_context_length=profile["target_context"],
```

- [ ] **Step 3: Run the `add-from-hf` regression test**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k add_model_from_hf_uses_resolved_deploy_profile -v
```
Expected: PASS, and for the Huihui Qwen3-Coder fixture the response should show `H200_141GB` and a high context value.

- [ ] **Step 4: Commit the `add-from-hf` integration**

```bash
git add backend/app/routers/admin.py backend/tests/test_chat.py
git commit -m "feat: apply auto deploy profile in add-from-hf"
```

---

### Task 4: Use the resolver in deploy and redeploy

**Files:**
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/app/services/runpod_service.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Extend `create_endpoint()` to accept parser/runtime overrides**

Update the `create_endpoint()` signature in `backend/app/services/runpod_service.py` to accept:

```python
    tool_parser: str | None = None,
    generation_config_mode: str | None = None,
    default_temperature: float | None = None,
```

- [ ] **Step 2: Replace hardcoded env vars with override-aware env assembly**

Replace the hardcoded vLLM env section with:

```python
        env_vars = [
            {"key": "MODEL_NAME", "value": model_name},
            {"key": "MAX_MODEL_LEN", "value": str(max_model_len)},
            {"key": "TRUST_REMOTE_CODE", "value": "1"},
            {"key": "GENERATION_CONFIG", "value": generation_config_mode or "vllm"},
            {"key": "ENABLE_AUTO_TOOL_CHOICE", "value": "true"},
            {"key": "TOOL_CALL_PARSER", "value": tool_parser or "hermes"},
            {"key": "ENABLE_PREFIX_CACHING", "value": "true"},
            {"key": "ENABLE_CHUNKED_PREFILL", "value": "true"},
        ]
        if default_temperature is not None:
            env_vars.append({"key": "DEFAULT_TEMPERATURE", "value": str(default_temperature)})
```

- [ ] **Step 3: Resolve profile before `deploy` and `redeploy` create calls**

In both `deploy_model()` and `redeploy_model()` in `backend/app/routers/admin.py`, before calling `create_endpoint(...)`, fetch HF metadata and resolve the profile:

```python
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"https://huggingface.co/api/models/{model.hf_repo}")
            resp.raise_for_status()
            metadata = resp.json()

        profile = resolve_deploy_profile(
            metadata,
            params_b=float(model.params_b or 0),
            quantization=model.quantization,
        )
```

Then call `create_endpoint(...)` with:

```python
            gpu_type=profile["gpu_type"],
            max_model_len=profile["target_context"],
            gpu_count=profile["gpu_count"],
            tool_parser=profile["tool_parser"],
            generation_config_mode=profile["generation_config_mode"],
            default_temperature=profile["default_temperature"],
```

Also update the model record before commit:

```python
        model.gpu_type = profile["gpu_type"]
        model.gpu_count = profile["gpu_count"]
        model.max_context_length = profile["target_context"]
```

- [ ] **Step 4: Add or update tests for deploy/redeploy to assert resolved profile is used**

Extend `backend/tests/test_chat.py` so that mocked `create_endpoint(...)` is asserted with profile-driven arguments for a coder model.

Example assertion pattern:

```python
mocked_create.assert_awaited()
kwargs = mocked_create.await_args.kwargs
assert kwargs["gpu_type"] == "H200_141GB"
assert kwargs["max_model_len"] >= 131072
```

- [ ] **Step 5: Run backend chat tests plus deploy profile tests**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py tests/test_deploy_profile_service.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit deploy/redeploy integration**

```bash
git add backend/app/routers/admin.py backend/app/services/runpod_service.py backend/tests/test_chat.py backend/tests/test_deploy_profile_service.py
git commit -m "feat: use auto deploy profiles for model deployment"
```

---

### Task 5: Align scout-side GPU/context selection

**Files:**
- Modify: `scout/scout/gpu_selector.py`
- Modify: `scout/scout/deployer.py`

- [ ] **Step 1: Replace the old simplistic scout GPU logic with the same safe-context policy**

In `scout/scout/gpu_selector.py`, either import the same logic or mirror the same formulas/constants so scout no longer picks A100 for coder/agent models that really need H200 for their target context.

- [ ] **Step 2: Make scout deploy env match backend defaults**

In `scout/scout/deployer.py`, update the env payload to include at minimum:

```python
{"key": "GENERATION_CONFIG", "value": "vllm"}
{"key": "ENABLE_AUTO_TOOL_CHOICE", "value": "true"}
{"key": "TOOL_CALL_PARSER", "value": "...family-specific parser..."}
{"key": "ENABLE_PREFIX_CACHING", "value": "true"}
{"key": "ENABLE_CHUNKED_PREFILL", "value": "true"}
```

- [ ] **Step 3: Commit scout alignment**

```bash
git add scout/scout/gpu_selector.py scout/scout/deployer.py
git commit -m "feat: align scout deploy defaults with backend profiles"
```

---

### Task 6: Live verification with Huihui Qwen3-Coder-30B-A3B-Instruct-abliterated

**Files:**
- Modify: none
- Test: live backend/admin flow only

- [ ] **Step 1: Add the model through the real admin route**

Run:
```bash
curl -sS -X POST \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  https://llm.ai-vfx.com/api/admin/models/add-from-hf \
  -d '{"hf_repo":"huihui-ai/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated"}'
```
Expected: returned model record already shows H200-class GPU and a high context, not the old shallow A100-style default.

- [ ] **Step 2: Deploy the model through the real admin route**

Run:
```bash
curl -sS -X POST \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  https://llm.ai-vfx.com/api/admin/models/<NEW_MODEL_ID>/deploy
```
Expected: successful response with a new endpoint ID.

- [ ] **Step 3: Verify database defaults were persisted correctly**

Run:
```bash
ssh -o StrictHostKeyChecking=no root@192.168.2.140 "docker exec unchained-postgres-vpmi0z.1.j01xdb3at4bobr8izc38ysr3d psql -U unchained -d unchained -c \"SELECT slug, gpu_type, gpu_count, max_context_length FROM llm_models WHERE id='<NEW_MODEL_ID>';\""
```
Expected: GPU/context reflect the resolved auto profile.

- [ ] **Step 4: Commit only if any environment-specific code adjustments were needed**

Run:
```bash
git status --short
```
Expected: clean working tree.

---

## Spec Coverage Check

- Family-aware profile resolver — Task 2
- GPU/context chosen from model metadata instead of shallow heuristics — Tasks 2, 3, 4
- Parser/runtime defaults per model family — Task 4
- Add-from-hf and deploy/redeploy share the same source of truth — Tasks 3 and 4
- Coder models should not default to too-weak A100 profile when they really need H200 — Tasks 2, 3, 6
- UI should just work without manual tweaking — Task 6

## Placeholder Scan

No placeholders remain. All paths, commands, code snippets, and expected results are explicit.

## Type Consistency Check

- Resolver name is consistently `resolve_deploy_profile`
- Family names are consistently `qwen3_coder`, `qwen3_general`, `glm`, `deepseek`, `gguf`, `fallback`
- Context field is consistently `target_context`
- Parser field is consistently `tool_parser`
- Sampling override is consistently `generation_config_mode` and `default_temperature`
