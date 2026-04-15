# Model Redeploy Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated admin endpoint that redeploys an existing model by deleting its current RunPod endpoint and creating a new one from the model settings stored in the database.

**Architecture:** Extend the existing admin router with a new explicit `POST /admin/models/{model_id}/redeploy` route. Reuse the current `delete_endpoint()` and `create_endpoint()` service functions so the new route follows the same backend deployment path as `/deploy`, but works for already-active models too. Validate behavior with focused router tests that mock RunPod calls.

**Tech Stack:** FastAPI, SQLAlchemy async session, pytest, FastAPI TestClient/AsyncClient patterns from existing backend tests, RunPod service helpers.

---

## File Structure

- **Modify:** `backend/app/routers/admin.py`
  - Add the new `redeploy_model()` route next to the existing `/deploy` route
  - Keep all redeploy orchestration in the router, reusing the existing service layer
- **Modify:** `backend/tests/test_chat.py`
  - Add focused admin router tests here instead of inventing a new test module, matching the current backend test footprint

---

### Task 1: Add failing redeploy tests

**Files:**
- Modify: `backend/tests/test_chat.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Read the current backend test patterns before editing**

Run:
```bash
python - <<'PY'
from pathlib import Path
p = Path('/Users/may/Uncensored_llm_api/backend/tests/test_chat.py')
print(p.read_text())
PY
```
Expected: existing auth/chat test patterns, fixtures, and monkeypatch style are visible.

- [ ] **Step 2: Add a failing test for successful redeploy**

Append a test like this to `backend/tests/test_chat.py` (adjust fixture names to match the file exactly):

```python
import uuid

from app.models.llm_model import LlmModel


async def test_admin_can_redeploy_active_model(client, admin_token, db_session, monkeypatch):
    model = LlmModel(
        id=uuid.uuid4(),
        slug="test-model",
        display_name="Test Model",
        hf_repo="test/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        status="active",
        runpod_endpoint_id="old-endpoint",
    )
    db_session.add(model)
    await db_session.commit()

    deleted = []

    async def fake_delete_endpoint(endpoint_id: str):
        deleted.append(endpoint_id)

    async def fake_create_endpoint(**kwargs):
        return {"data": {"saveEndpoint": {"id": "new-endpoint"}}}

    monkeypatch.setattr("app.routers.admin.delete_endpoint", fake_delete_endpoint)
    monkeypatch.setattr("app.routers.admin.create_endpoint", fake_create_endpoint)

    response = await client.post(
        f"/admin/models/{model.id}/redeploy",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Model redeployed",
        "endpoint_id": "new-endpoint",
    }

    await db_session.refresh(model)
    assert deleted == ["old-endpoint"]
    assert model.runpod_endpoint_id == "new-endpoint"
    assert model.status == "active"
```

- [ ] **Step 3: Add a failing test for missing model**

Add a second test in `backend/tests/test_chat.py`:

```python
async def test_redeploy_returns_404_for_missing_model(client, admin_token):
    response = await client.post(
        "/admin/models/00000000-0000-0000-0000-000000000000/redeploy",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Model not found"
```

- [ ] **Step 4: Add a failing test for redeploy failure path**

Add a third test in `backend/tests/test_chat.py`:

```python
async def test_redeploy_marks_model_inactive_on_create_failure(client, admin_token, db_session, monkeypatch):
    model = LlmModel(
        id=uuid.uuid4(),
        slug="broken-model",
        display_name="Broken Model",
        hf_repo="broken/model",
        params_b=7,
        quantization="FP16",
        gpu_type="H100_80GB",
        gpu_count=1,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        status="active",
        runpod_endpoint_id="old-endpoint",
    )
    db_session.add(model)
    await db_session.commit()

    async def fake_delete_endpoint(endpoint_id: str):
        return None

    async def fake_create_endpoint(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.routers.admin.delete_endpoint", fake_delete_endpoint)
    monkeypatch.setattr("app.routers.admin.create_endpoint", fake_create_endpoint)

    response = await client.post(
        f"/admin/models/{model.id}/redeploy",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Deployment failed: boom"

    await db_session.refresh(model)
    assert model.status == "inactive"
    assert model.runpod_endpoint_id is None
```

- [ ] **Step 5: Run the new tests to verify they fail**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k redeploy -v
```
Expected: FAIL with `404 Not Found` for the missing route or similar route-not-implemented failures.

- [ ] **Step 6: Commit the failing tests**

```bash
git add backend/tests/test_chat.py
git commit -m "test: add failing coverage for model redeploy route"
```

---

### Task 2: Implement the redeploy route in admin router

**Files:**
- Modify: `backend/app/routers/admin.py:200-258`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Add the new route directly below the existing `/deploy` handler**

Insert this code into `backend/app/routers/admin.py` after `deploy_model()` and before `update_model_status()`:

```python
@router.post("/models/{model_id}/redeploy")
async def redeploy_model(
    model_id: uuid.UUID,
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(LlmModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    model.status = "deploying"
    await db.commit()

    try:
        if model.runpod_endpoint_id:
            await delete_endpoint(model.runpod_endpoint_id)
            model.runpod_endpoint_id = None
            await db.commit()

        result = await create_endpoint(
            name=f"unch-{model.slug}",
            gpu_type=model.gpu_type,
            model_name=model.hf_repo,
            params_b=float(model.params_b or 0),
            max_model_len=model.max_context_length or 4096,
            gpu_count=model.gpu_count or 1,
            db=db,
        )
        endpoint_data = result.get("data", {}).get("saveEndpoint", {})
        model.runpod_endpoint_id = endpoint_data.get("id")
        model.status = "active"
    except Exception as e:
        model.status = "inactive"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Deployment failed: {e}")

    await db.commit()
    return {"detail": "Model redeployed", "endpoint_id": model.runpod_endpoint_id}
```

- [ ] **Step 2: Run the redeploy tests**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -k redeploy -v
```
Expected: all three redeploy tests PASS.

- [ ] **Step 3: Run the full backend test file to verify no regression in nearby routes**

Run:
```bash
cd /Users/may/Uncensored_llm_api/backend && pytest tests/test_chat.py -v
```
Expected: PASS for existing chat tests plus the new redeploy tests.

- [ ] **Step 4: Commit the route implementation**

```bash
git add backend/app/routers/admin.py backend/tests/test_chat.py
git commit -m "feat: add admin model redeploy route"
```

---

### Task 3: Verify redeploy route against the running backend

**Files:**
- Modify: none
- Test: running backend route only

- [ ] **Step 1: Find a real active model ID in the target environment**

Run:
```bash
ssh -o StrictHostKeyChecking=no root@192.168.2.140 "docker exec unchained-postgres-vpmi0z.1.j01xdb3at4bobr8izc38ysr3d psql -U unchained -d unchained -c \"SELECT id, slug, status, runpod_endpoint_id FROM llm_models WHERE status='active';\""
```
Expected: one or more active models with UUIDs.

- [ ] **Step 2: Trigger redeploy through the backend route, not with docker-exec Python**

Run:
```bash
curl -sS -X POST \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  https://llm.ai-vfx.com/api/admin/models/<MODEL_UUID>/redeploy
```
Expected: JSON like:
```json
{"detail":"Model redeployed","endpoint_id":"<new-id>"}
```

- [ ] **Step 3: Verify the database reflects the new endpoint**

Run:
```bash
ssh -o StrictHostKeyChecking=no root@192.168.2.140 "docker exec unchained-postgres-vpmi0z.1.j01xdb3at4bobr8izc38ysr3d psql -U unchained -d unchained -c \"SELECT id, slug, status, runpod_endpoint_id FROM llm_models WHERE id='<MODEL_UUID>';\""
```
Expected: `status = active` and `runpod_endpoint_id` equals the route response.

- [ ] **Step 4: Commit any remaining test-related adjustments only if needed**

```bash
git status --short
```
Expected: no unstaged changes. If there are environment-specific fixes, stage only the intended files and commit with a focused message.

---

## Spec Coverage Check

- Explicit admin route for redeploy — covered in Task 2
- Delete old endpoint before creating new one — covered in Task 2
- Use current DB model settings for create flow — covered in Task 2
- Failure path sets `inactive` — covered in Task 1 + Task 2
- Validate against live backend route — covered in Task 3

## Placeholder Scan

No TBD/TODO placeholders remain. All file paths, code, commands, and expected outcomes are explicit.

## Type Consistency Check

- Route name: `redeploy_model`
- Path: `/models/{model_id}/redeploy`
- Success detail: `Model redeployed`
- Failure detail: `Deployment failed: {e}`
- Endpoint ID field name is consistently `endpoint_id`
