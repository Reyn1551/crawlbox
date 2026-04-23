import pytest
@pytest.mark.asyncio
async def test_health(client):
    r=await client.get("/api/v1/health");assert r.status_code==200
@pytest.mark.asyncio
async def test_index(client):
    r=await client.get("/");assert r.status_code==200;assert "SentimentTools" in r.text
@pytest.mark.asyncio
async def test_empty(client):
    r=await client.post("/api/v1/analysis",json={"urls":[]});assert r.status_code==400
@pytest.mark.asyncio
async def test_invalid(client):
    r=await client.post("/api/v1/analysis",json={"urls":["x"]});assert r.status_code==400
@pytest.mark.asyncio
async def test_404(client):
    r=await client.get("/job/nope");assert r.status_code==404