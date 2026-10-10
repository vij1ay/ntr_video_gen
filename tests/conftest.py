"""Pytest configuration and shared fixtures."""
import pytest


@pytest.fixture(autouse=True)
def reset_config():
    """Reset the AppConfig singleton between tests."""
    from app.core.config import reset_config
    yield
    reset_config()
