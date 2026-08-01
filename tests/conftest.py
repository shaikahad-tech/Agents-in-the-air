"""Pytest fixtures shared across all test modules."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add backend to path
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# Set test env BEFORE importing app modules
os.environ["AITA_ENV"] = "development"
os.environ["AITA_API_KEY"] = ""  # disable auth in tests
os.environ["AITA_RATE_LIMIT_ENABLED"] = "false"
os.environ["AITA_DATA_DIR"] = tempfile.mkdtemp(prefix="aita-test-data-")
os.environ["AITA_WORKSPACE_DIR"] = tempfile.mkdtemp(prefix="aita-test-ws-")
os.environ["AITA_MAX_CONCURRENT_NODES"] = "5"
os.environ["AITA_DEFAULT_NODE_TIMEOUT"] = "10"
os.environ["AITA_OPENAI_API_KEY"] = "test-key-not-real"
os.environ["OPENAI_API_KEY"] = "test-key-not-real"


@pytest.fixture
def settings():
    """Fresh settings per test (bypasses lru_cache)."""
    from app.config import Settings
    s = Settings()
    s.ensure_dirs()
    return s


@pytest.fixture
def executor(settings):
    from app.executor import WorkflowExecutor
    return WorkflowExecutor(settings=settings)


@pytest.fixture
def client(settings):
    """FastAPI test client with auth disabled."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
