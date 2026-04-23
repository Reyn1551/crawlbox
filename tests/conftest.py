import asyncio,pytest
from httpx import AsyncClient,ASGITransport
from src.main import app
from src.database import engine
from src.models import Base
@pytest.fixture(scope="session")
def event_loop():
    loop=asyncio.new_event_loop();yield loop;loop.close()
@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as c:await c.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as c:await c.run_sync(Base.metadata.drop_all)
@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as ac:yield ac