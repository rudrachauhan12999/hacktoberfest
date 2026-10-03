"""Shared fixtures and sample model answers."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image


def label_reading(**changes) -> dict:
    """A plausible per-serving label reading; pass fields to override."""
    reading = {
        "product_name": "Masala Chips",
        "basis": "per_serving",
        "serving_size_g": 30,
        "calories": 160,
        "energy_kj": None,
        "protein_g": 2,
        "carbs_g": 15,
        "sugar_g": 1,
        "fat_g": 10,
        "fiber_g": 1,
        "sodium_mg": 170,
        "salt_g": None,
        "ingredients": ["potato", "sunflower oil", "salt", "spices"],
        "contains": [],
        "may_contain": [],
    }
    reading.update(changes)
    return reading


def meal_reading(**changes) -> dict:
    """A plausible meal estimate; pass fields to override."""
    reading = {
        "dish_name": "Dal with rice",
        "items": [{"name": "dal", "portion": "1 bowl"}, {"name": "rice", "portion": "1 cup"}],
        "calories_min": 400, "calories_max": 500,
        "protein_g_min": 15, "protein_g_max": 20,
        "carbs_g_min": 50, "carbs_g_max": 60,
        "fat_g_min": 14, "fat_g_max": 18,
        "likely_ingredients": ["toor dal", "rice", "sunflower oil", "cumin"],
    }
    reading.update(changes)
    return reading


def item(source: str = "label", **changes) -> dict:
    """A normalised item with known nutrients; pass fields to override."""
    def exact(value):
        return {"lo": value, "hi": value}

    base = {
        "source": source,
        "name": "Test food",
        "nutrients": {
            "calories": exact(200), "protein_g": exact(30), "carbs_g": exact(20),
            "sugar_g": exact(5), "fat_g": exact(5), "fiber_g": exact(2), "sodium_mg": exact(100),
        },
        "ingredients": ["rice", "salt"],
        "contains": [],
        "may_contain": [],
        "items": [],
        "notes": [],
    }
    base.update(changes)
    return base


class FakeChat:
    """Stands in for ollama_client.chat. Replies are given in order; calls are recorded."""

    def __init__(self, *replies):
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        self.calls: list[tuple[list, dict | None]] = []

    def __call__(self, messages, schema=None):
        self.calls.append(([dict(m) for m in messages], schema))
        if len(self.calls) > len(self.replies):
            raise AssertionError("the model was called more times than expected")
        return self.replies[len(self.calls) - 1]


def png_bytes(size=(1200, 800)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def client(monkeypatch):
    """An API client on an empty in-memory database, with Ollama reported as ready."""
    from fastapi.testclient import TestClient

    from app import db, ollama_client
    from app.main import app

    db.init_db("sqlite://")
    monkeypatch.setattr(ollama_client, "require_ready", lambda: None)
    with TestClient(app) as test_client:
        yield test_client
