# Strict OpenAI Streaming Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/v1/chat/completions` streaming fully OpenAI-compatible by removing custom `status` SSE events so strict external clients like `opencode` can parse the stream without type errors.

**Architecture:** Remove all custom `object: "status"` events from the OpenAI-compatible streaming path and keep only standard `chat.completion.chunk` objects plus `[DONE]`. Keep worker state visibility in the already-existing `/v1/models/{slug}/status` endpoint, and update any internal consumer that depended on stream-status events to use the dedicated status endpoint instead.

**Tech Stack:** FastAPI, StreamingResponse/SSE, existing chat/playground router, existing proxy streaming path, pytest.

---

## File Structure

- **Modify:** `backend/app/services/proxy_service.py`
  - Remove non-OpenAI status objects from `proxy_chat_completion_stream()`
- **Modify:** `backend/app/routers/playground.py`
  - Stop depending on `object: status` stream events for billing/output assembly
- **Modify:** `backend/tests/test_chat.py`
  - Add regression coverage for strict stream shape
- **Create:** `backend/tests/test_streaming_openai_compat.py`
  - Focused tests that assert no `object: status` chunks are emitted

---

### Task 1: Add failing tests for strict OpenAI stream shape

**Files:**
- Create: `backend/tests/test_streaming_openai_compat.py`
- Test: `backend/tests/test_streaming_openai_compat.py`

- [ ] **Step 1: Create a focused streaming test module**

Create `backend/tests/test_streaming_openai_compat.py` with this scaffold:

```python
import json

import pytest

from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest, ChatMessage
from app.services import proxy_service


@pytest.mark.asyncio
async def test_stream_emits_only_openai_chunks(monkeypatch):
    model = LlmModel(
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        runpod_endpoint_id="endpoint-1",
        max_context_length=4096,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    async def fake_stream_inference(endpoint_id, payload):
        yield "hello"

    async def fake_check_worker_status(endpoint_id):
        return {"ready": False, "status": "warming_up", "estimated_wait": 120}

    monkeypatch.setattr("app.services.runpod_service.stream_inference", fake_stream_inference)
    monkeypatch.setattr("app.services.runpod_service.check_worker_status", fake_check_worker_status)

    chunks = []
    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        chunks.append(chunk)

    decoded = [c[6:] for c in chunks if c.startswith("data: ") and c.strip() != "data: [DONE]"]
    payloads = [json.loads(c) for c in decoded]

    assert all(p["object"] == "chat.completion.chunk" for p in payloads)
    assert all("choices" in p for p in payloads)
```

- [ ] **Step 2: Add a test proving status objects are not present**

Append this test to `backend/tests/test_streaming_openai_compat.py`:

```python
@pytest.mark.asyncio
async def test_stream_never_emits_object_status(monkeypatch):
    model = LlmModel(
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        runpod_endpoint_id="endpoint-1",
        max_context_length=4096,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    async def fake_stream_inference(endpoint_id, payload):
        yield "__STATUS:{\"status\":\"IN_QUEUE\",\"message\":\"Waiting\",\"elapsed\":10}"
        yield "hello"

    async def fake_check_worker_status(endpoint_id):
        return {"ready": False, "status": "idle", "estimated_wait": 60}

    monkeypatch.setattr("app.services.runpod_service.stream_inference", fake_stream_inference)
    monkeypatch.setattr("app.services.runpod_service.check_worker_status", fake_check_worker_status)

    chunks = []
    async for chunk in proxy_service.proxy_chat_completion_stream(request, model):
        chunks.append(chunk)

    decoded = [c[6:] for c in chunks if c.startswith("data: ") and c.strip() != "data: [DONE]"]
    assert all(json.loads(c).get("object") != "status" for c in decoded)
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_streaming_openai_compat.py -v
```
Expected: FAIL because the current implementation still emits `object: "status"` chunks.

- [ ] **Step 4: Commit the failing stream tests**

```bash
git add backend/tests/test_streaming_openai_compat.py
git commit -m "test: add failing coverage for strict openai streaming"
```

---

### Task 2: Remove custom status events from the OpenAI stream path

**Files:**
- Modify: `backend/app/services/proxy_service.py`
- Test: `backend/tests/test_streaming_openai_compat.py`

- [ ] **Step 1: Remove the preflight status event block**

In `backend/app/services/proxy_service.py`, delete this entire block from `proxy_chat_completion_stream()`:

```python
    worker_status = await runpod_service.check_worker_status(model.runpod_endpoint_id)
    if not worker_status["ready"]:
        status_event = {
            "object": "status",
            "status": worker_status["status"],
            "message": _status_message(worker_status["status"]),
            "estimated_wait": worker_status["estimated_wait"],
        }
        yield f"data: {json.dumps(status_event)}\n\n"
```

Replace it with just:

```python
    worker_status = await runpod_service.check_worker_status(model.runpod_endpoint_id)
```

- [ ] **Step 2: Remove status-marker emission from the stream loop**

Delete this block entirely:

```python
        if text_chunk.startswith("__STATUS:"):
            status_data = json.loads(text_chunk[9:])
            status_event = {
                "object": "status",
                "status": status_data.get("status", "unknown"),
                "message": status_data.get("message", ""),
                "elapsed": status_data.get("elapsed", 0),
            }
            yield f"data: {json.dumps(status_event)}\n\n"
            continue
```

- [ ] **Step 3: Remove the synthetic `ready` event**

Delete this block:

```python
        if not first_token_received:
            first_token_received = True
            if not worker_status["ready"]:
                ready_event = {"object": "status", "status": "ready", "message": "Worker ready, generating..."}
                yield f"data: {json.dumps(ready_event)}\n\n"
```

Replace it with:

```python
        if not first_token_received:
            first_token_received = True
```

- [ ] **Step 4: Run the strict streaming tests**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_streaming_openai_compat.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit the streaming compatibility fix**

```bash
git add backend/app/services/proxy_service.py backend/tests/test_streaming_openai_compat.py
git commit -m "fix(api): remove custom status events from openai stream"
```

---

### Task 3: Verify existing chat tests still pass

**Files:**
- Modify: none
- Test: `backend/tests/test_chat.py`
- Test: `backend/tests/test_streaming_openai_compat.py`

- [ ] **Step 1: Run the existing chat test file**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -v
```
Expected: PASS.

- [ ] **Step 2: Run both test files together**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py tests/test_streaming_openai_compat.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit only if additional test cleanups were required**

```bash
git status --short
```
Expected: clean working tree.

---

### Task 4: Check whether playground depends on stream-status events

**Files:**
- Modify: `backend/app/routers/playground.py` only if needed
- Test: `backend/app/routers/playground.py`

- [ ] **Step 1: Inspect the existing playground stream consumer**

Read `backend/app/routers/playground.py` and verify whether it requires `object: "status"` chunks for correctness, or merely passes them through.

- [ ] **Step 2: If playground only forwards status chunks, remove the dependency**

If you find logic like:

```python
if data.get("object") == "status":
    yield chunk
    continue
```

remove the special handling so the route only aggregates normal OpenAI deltas and forwards chunks transparently.

- [ ] **Step 3: If no change is needed, leave playground untouched**

Do not edit the file unless the strict-streaming change would otherwise break billing/output handling.

- [ ] **Step 4: Commit any required playground adjustment**

```bash
git add backend/app/routers/playground.py
git commit -m "fix(playground): remove dependency on custom stream status events"
```

Only do this if the file actually changed.

---

### Task 5: Live verification against a strict client workflow

**Files:**
- Modify: none
- Test: live backend only

- [ ] **Step 1: Push the branch and trigger deployment**

Run:
```bash
git push
curl -sS -X POST \
  -H "x-api-key: XdVofMdOfAlneojMFpBWplFeYWbxFzcUpuPBlQLYuBxmfWmjARKNyXwDEnsgMrZc" \
  -H "Content-Type: application/json" \
  http://192.168.2.140:3001/api/compose.redeploy \
  -d '{"composeId":"VHHK57itWhpLr8xIXq53q"}'
```
Expected: backend redeploy queued.

- [ ] **Step 2: Re-run the problematic strict-client flow**

Use the Huihui model and send the same `opencode` request that previously failed with:

```text
Type validation failed: Value: {"object":"status", ...}
```

Expected: no validation error, because the stream should now only contain `chat.completion.chunk` objects.

- [ ] **Step 3: Verify status info is still available out-of-band**

Run:
```bash
curl -sS https://llm.ai-vfx.com/api/v1/models/huihui-ai-huihui-qwen3-coder-30b-a3b-instruct-abliterated/status
```
Expected: worker state still comes from this endpoint, not from the chat stream.

- [ ] **Step 4: Commit only if environment-specific code changed during verification**

```bash
git status --short
```
Expected: clean working tree.

---

## Spec Coverage Check

- `/v1/chat/completions` stream must be strict OpenAI — Task 2
- `object: status` must disappear from the stream — Task 2 + Task 1
- `/v1/models/{slug}/status` remains the place for worker state — Task 5
- strict clients like `opencode` should stop failing validation — Task 5
- internal UI/playground dependencies must be checked — Task 4

## Placeholder Scan

No placeholders remain. Files, code, commands, and expected outcomes are explicit.

## Type Consistency Check

- stream object type is consistently `chat.completion.chunk`
- banned object type is consistently `status`
- relevant endpoint is consistently `/v1/chat/completions`
- worker-state endpoint is consistently `/v1/models/{slug}/status`
