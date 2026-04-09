import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine, Session

from app.main import app

# Use in-memory SQLite for all tests
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="session", autouse=True)
def session_fixture(monkeypatch, request):
    monkeypatch.setenv("FERRYMAN_BEARER_TOKEN", "test-bearer-token")

    # Use real DB for live tests to allow debugging/persistence
    if "test_live" in request.node.name:
        from app.core.db import get_session
        # get_session is a generator, we need to enter its context
        with get_session() as real_session:
            yield real_session
        return

    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Patch the real engine in app.core.db
    import app.core.db
    monkeypatch.setattr(app.core.db, "engine", engine)
    
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client")
def client_fixture(session):
    # Override any dependencies if needed (e.g., get_session)
    def get_session_override():
        return session
    
    # We could use app.dependency_overrides here if needed
    with TestClient(app) as c:
        yield c

@pytest.fixture(name="mock_model")
def mock_model_fixture():
    return TestModel()
