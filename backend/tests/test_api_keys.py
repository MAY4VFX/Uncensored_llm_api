import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient, auth_headers):
    resp = await client.post("/api-keys", json={"name": "Test Key"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_key"].startswith("sk-unch-")
    assert data["name"] == "Test Key"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient, auth_headers):
    # Create a key
    await client.post("/api-keys", json={"name": "Key 1"}, headers=auth_headers)

    resp = await client.get("/api-keys", headers=auth_headers)
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) >= 1
    assert keys[0]["name"] == "Key 1"
    # Raw key should NOT be returned in list
    assert "raw_key" not in keys[0]


@pytest.mark.asyncio
async def test_revoke_api_key(client: AsyncClient, auth_headers):
    # Create
    create_resp = await client.post("/api-keys", json={"name": "Revoke Me"}, headers=auth_headers)
    key_id = create_resp.json()["id"]

    # Revoke
    resp = await client.delete(f"/api-keys/{key_id}", headers=auth_headers)
    assert resp.status_code == 200

    # Verify revoked
    list_resp = await client.get("/api-keys", headers=auth_headers)
    keys = list_resp.json()
    revoked = [k for k in keys if k["id"] == key_id]
    assert len(revoked) == 1
    assert revoked[0]["is_active"] is False


@pytest.mark.asyncio
async def test_create_key_no_auth(client: AsyncClient):
    resp = await client.post("/api-keys", json={"name": "No Auth"})
    assert resp.status_code == 422
