import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from sqlmodel import SQLModel, create_engine, Session

from app.main import app

# Use in-memory SQLite for all tests
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="session", autouse=True)
def session_fixture(monkeypatch, request):
    # Skip in-memory DB for live tests to allow debugging/persistence
    if "test_live" in request.node.name:
        yield None
        return

    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
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
