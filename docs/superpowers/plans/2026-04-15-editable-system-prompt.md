# Editable Model System Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a model-level editable `system_prompt` that can be changed through the admin API and is applied automatically in both `/v1/chat/completions` and `/playground/chat` without redeploying the model endpoint.

**Architecture:** Store `system_prompt` directly on `llm_models`, expose it through admin model schemas and a new admin update route, then merge it with any client-provided `system` message inside `proxy_service._build_vllm_payload()`. The merge rule is: model prompt first, client system prompt second, combined into a single `system` message before sending to vLLM.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, existing backend admin/chat/playground flows.

---

## File Structure

- **Modify:** `backend/app/models/llm_model.py`
  - Add persistent `system_prompt` column to the model
- **Create:** `backend/alembic/versions/<timestamp>_add_system_prompt_to_llm_models.py`
  - Database migration for the new nullable text column
- **Modify:** `backend/app/schemas/model.py`
  - Expose `system_prompt` in model response and update request schema
- **Modify:** `backend/app/routers/admin.py`
  - Add admin update route for editable model fields, including `system_prompt`
- **Modify:** `backend/app/services/proxy_service.py`
  - Merge model-level prompt with client system prompt before proxying to vLLM
- **Modify:** `backend/tests/test_chat.py`
  - Add regression tests for prompt merge behavior and admin update path

---

### Task 1: Add failing tests for editable model prompt

**Files:**
- Modify: `backend/tests/test_chat.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Read the current test file before editing**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && python - <<'PY'
from pathlib import Path
print(Path('tests/test_chat.py').read_text())
PY
```
Expected: existing chat/admin-style tests are visible.

- [ ] **Step 2: Add a failing unit-style test for merging model prompt with client system prompt**

Append this test to `backend/tests/test_chat.py`:

```python
from app.models.llm_model import LlmModel
from app.schemas.openai import ChatCompletionRequest, ChatMessage
from app.services.proxy_service import _build_vllm_payload


@pytest.mark.asyncio
async def test_build_vllm_payload_merges_model_prompt_and_client_system():
    model = LlmModel(
        id=uuid.uuid4(),
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        system_prompt="Always answer in the user's language.",
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[
            ChatMessage(role="system", content="Be concise."),
            ChatMessage(role="user", content="Привет"),
        ],
    )

    payload = _build_vllm_payload(request, model)
    messages = payload["openai_input"]["messages"]

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Always answer in the user's language.\n\n---\n\nBe concise."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Привет"
```

- [ ] **Step 3: Add a failing test for model prompt when no client system exists**

Append this test to `backend/tests/test_chat.py`:

```python
@pytest.mark.asyncio
async def test_build_vllm_payload_injects_model_prompt_when_client_has_no_system():
    model = LlmModel(
        id=uuid.uuid4(),
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="active",
        system_prompt="Reply in the same language as the user.",
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    payload = _build_vllm_payload(request, model)
    messages = payload["openai_input"]["messages"]

    assert messages[0] == {
        "role": "system",
        "content": "Reply in the same language as the user.",
    }
    assert messages[1]["role"] == "user"
```

- [ ] **Step 4: Add a failing admin route test for updating `system_prompt`**

Append this test to `backend/tests/test_chat.py`:

```python
@pytest.mark.asyncio
async def test_admin_can_update_model_system_prompt(client: AsyncClient, admin_headers, db_session):
    model = LlmModel(
        id=uuid.uuid4(),
        slug="prompt-model",
        display_name="Prompt Model",
        hf_repo="prompt/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        status="inactive",
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
    )
    db_session.add(model)
    await db_session.commit()

    response = await client.patch(
        f"/admin/models/{model.id}",
        headers=admin_headers,
        json={"system_prompt": "Always answer in Russian."},
    )

    assert response.status_code == 200
    await db_session.refresh(model)
    assert model.system_prompt == "Always answer in Russian."
```

- [ ] **Step 5: Run the new tests to verify they fail**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k "system_prompt or build_vllm_payload or admin_can_update_model_system_prompt" -v
```
Expected: FAIL because `system_prompt` field and `/admin/models/{id}` PATCH route do not exist yet.

- [ ] **Step 6: Commit the failing tests**

```bash
git add backend/tests/test_chat.py
git commit -m "test: add failing coverage for editable model system prompt"
```

---

### Task 2: Add persistent `system_prompt` to the model and schemas

**Files:**
- Modify: `backend/app/models/llm_model.py`
- Create: `backend/alembic/versions/<timestamp>_add_system_prompt_to_llm_models.py`
- Modify: `backend/app/schemas/model.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Add the nullable column to `LlmModel`**

In `backend/app/models/llm_model.py`, add this field near `description`:

```python
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Create the Alembic migration**

Create `backend/alembic/versions/<timestamp>_add_system_prompt_to_llm_models.py` with:

```python
"""add system_prompt to llm_models

Revision ID: <new_revision_id>
Revises: <previous_revision_id>
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = "<new_revision_id>"
down_revision = "<previous_revision_id>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_models", sa.Column("system_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_models", "system_prompt")
```

- [ ] **Step 3: Expose `system_prompt` in the response schema**

In `backend/app/schemas/model.py`, add the field to `ModelResponse`:

```python
    system_prompt: str | None = None
```

- [ ] **Step 4: Add an update request schema**

In `backend/app/schemas/model.py`, add:

```python
class UpdateModelRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    gpu_type: str | None = None
    gpu_count: int | None = None
    max_context_length: int | None = None
    system_prompt: str | None = None
```

- [ ] **Step 5: Run the targeted tests again**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k "system_prompt or build_vllm_payload or admin_can_update_model_system_prompt" -v
```
Expected: still FAIL, but now because the admin update route and merge logic are not implemented yet.

- [ ] **Step 6: Commit model/schema groundwork**

```bash
git add backend/app/models/llm_model.py backend/app/schemas/model.py backend/alembic/versions/*.py
git commit -m "feat: add persistent model system prompt field"
```

---

### Task 3: Add admin API to update model fields including `system_prompt`

**Files:**
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/app/schemas/model.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Import the new update schema**

In `backend/app/routers/admin.py`, update the import line to include `UpdateModelRequest`:

```python
from app.schemas.model import (
    AddFromHfRequest,
    CreateModelRequest,
    ModelResponse,
    UpdateModelRequest,
    UpdateModelStatusRequest,
)
```

- [ ] **Step 2: Add the PATCH update route**

Insert this route in `backend/app/routers/admin.py`, above the deploy routes:

```python
@router.patch("/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: uuid.UUID,
    request: UpdateModelRequest,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    updates = request.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(model, field, value)

    await db.commit()
    await db.refresh(model)
    return model
```

- [ ] **Step 3: Run the update-route test**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k admin_can_update_model_system_prompt -v
```
Expected: PASS.

- [ ] **Step 4: Commit the admin API change**

```bash
git add backend/app/routers/admin.py backend/app/schemas/model.py backend/tests/test_chat.py
git commit -m "feat: add admin model update route"
```

---

### Task 4: Merge model prompt with client system prompt in proxy path

**Files:**
- Modify: `backend/app/services/proxy_service.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Add a helper that merges model and client system prompts**

In `backend/app/services/proxy_service.py`, add this helper above `_build_vllm_payload()`:

```python
def _merge_system_prompts(model_prompt: str | None, messages: list[ChatMessage]) -> list[dict]:
    client_system_parts: list[str] = []
    non_system_messages: list[dict] = []

    for m in messages:
        if m.role == "system":
            if m.content:
                client_system_parts.append(m.content)
            continue

        item: dict = {"role": m.role, "content": m.content}
        if m.name:
            item["name"] = m.name
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            item["tool_calls"] = m.tool_calls
        non_system_messages.append(item)

    merged_parts: list[str] = []
    if model_prompt:
        merged_parts.append(model_prompt)
    if client_system_parts:
        merged_parts.append("\n\n---\n\n".join(client_system_parts))

    if merged_parts:
        return [{"role": "system", "content": "\n\n---\n\n".join(merged_parts)}, *non_system_messages]
    return non_system_messages
```

- [ ] **Step 2: Replace the current `messages_out` assembly**

In `_build_vllm_payload()`, replace the loop that manually builds `messages_out` with:

```python
    messages_out = _merge_system_prompts(model.system_prompt, request.messages)
```

- [ ] **Step 3: Run the prompt-merge tests**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k "system_prompt or build_vllm_payload" -v
```
Expected: PASS.

- [ ] **Step 4: Run the whole chat test file**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit the merge logic**

```bash
git add backend/app/services/proxy_service.py backend/tests/test_chat.py
git commit -m "feat: apply editable model system prompt in proxy path"
```

---

### Task 5: Verify end-to-end through admin API and playground-compatible path

**Files:**
- Modify: none
- Test: live backend + DB verification only

- [ ] **Step 1: Apply the migration in the running backend environment**

Run:
```bash
ssh -o StrictHostKeyChecking=no root@192.168.2.140 "docker exec compose-navigate-haptic-port-fuoks6-backend-1 alembic upgrade head"
```
Expected: migration applies successfully.

- [ ] **Step 2: Update a real model via admin API**

Run:
```bash
curl -sS -X PATCH \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  https://llm.ai-vfx.com/api/admin/models/<MODEL_UUID> \
  -d '{"system_prompt":"You must answer in the same language as the user's latest message. Do not switch languages unless explicitly asked. Do not translate code, identifiers, or quoted text unless asked."}'
```
Expected: response includes the updated `system_prompt` field.

- [ ] **Step 3: Verify the database stores the prompt**

Run:
```bash
ssh -o StrictHostKeyChecking=no root@192.168.2.140 "docker exec unchained-postgres-vpmi0z.1.j01xdb3at4bobr8izc38ysr3d psql -U unchained -d unchained -c \"SELECT id, slug, system_prompt FROM llm_models WHERE id='<MODEL_UUID>';\""
```
Expected: `system_prompt` contains the text from Step 2.

- [ ] **Step 4: Verify normal API path respects the stored prompt**

Run:
```bash
curl -sS -X POST \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  https://llm.ai-vfx.com/api/v1/chat/completions \
  -d '{"model":"<MODEL_SLUG>","messages":[{"role":"user","content":"Привет, ответь одним словом"}],"max_tokens":16}'
```
Expected: assistant responds in Russian.

- [ ] **Step 5: Verify client system prompt is merged, not replaced**

Run:
```bash
curl -sS -X POST \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  https://llm.ai-vfx.com/api/v1/chat/completions \
  -d '{"model":"<MODEL_SLUG>","messages":[{"role":"system","content":"Be extremely concise."},{"role":"user","content":"Привет"}],"max_tokens":16}'
```
Expected: answer stays in Russian and is concise, showing both prompts were honored.

---

## Spec Coverage Check

- Prompt stored per model in DB — covered in Task 2
- Prompt editable through admin API — covered in Task 3
- Applied in both standard API and playground path — covered in Task 4 (shared proxy path)
- No redeploy required — covered by Task 5 using PATCH only
- Client system prompt merged into a single system message — covered in Task 4 and Task 5

## Placeholder Scan

No TBD/TODO placeholders remain. All files, commands, code snippets, and expected outputs are explicit.

## Type Consistency Check

- Stored field name is consistently `system_prompt`
- Update schema is consistently `UpdateModelRequest`
- Admin update route path is consistently `PATCH /admin/models/{model_id}`
- Merge helper name is consistently `_merge_system_prompts`
- Separator is consistently `\n\n---\n\n`
