"""Disable live Binance and the PM pipeline during unit tests."""

import pytest

from app.config import settings
from app.pipeline import detach

settings.boot_binance = False


@pytest.fixture(autouse=True)
def _disable_live_pipeline():
    detach()
    yield
    detach()
