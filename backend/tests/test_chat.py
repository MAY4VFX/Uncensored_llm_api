import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_models(client: AsyncClient):
    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_chat_completion_no_auth(client: AsyncClient):
    resp = await client.post("/v1/chat/completions", json={
        "model": "some-model",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert resp.status_code == 422  # Missing auth header


@pytest.mark.asyncio
async def test_chat_completion_invalid_key(client: AsyncClient):
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "some-model",
            "messages": [{"role": "user", "content": "Hello"}],
        },
        headers={"Authorization": "Bearer sk-unch-invalidkey"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
