"""The API, with the Ollama client replaced by fakes."""

import json
from datetime import date, timedelta

import pytest

from app import explain, extract, ollama_client

from .conftest import FakeChat, item, label_reading, meal_reading, png_bytes

SUMMARY = {"summary": "This fits your goals. Protein is a little low."}


def use_model(monkeypatch, *replies) -> FakeChat:
    chat = FakeChat(*replies)
    monkeypatch.setattr(ollama_client, "chat", chat)
    return chat


def upload(name="label.png"):
    return {"image": (name, png_bytes(), "image/png")}


# ------------------------------------------------------- health and profile


def test_health_reports_model_status(client, monkeypatch):
    monkeypatch.setattr(ollama_client, "health", lambda: {
        "host": "http://127.0.0.1:11434", "model": "gemma4:e4b",
        "reachable": True, "model_installed": False, "message": "Run ollama pull gemma4:e4b",
    })
    body = client.get("/api/health").json()
    assert body["app"] == "ok"
    assert body["reachable"] is True and body["model_installed"] is False


def test_profile_is_unconfigured_until_saved(client):
    first = client.get("/api/profile").json()
    assert first["configured"] is False
    assert first["calories"] == 2000 and first["meals_per_day"] == 3

    saved = client.put("/api/profile", json={"name": "Asha", "diet": "jain",
                                             "allergens": "peanut, dairy", "sugar_g_max": None})
    assert saved.status_code == 200
    body = client.get("/api/profile").json()
    assert body["configured"] is True
    assert body["allergens"] == ["peanut", "dairy"]
    assert body["sugar_g_max"] is None


def test_profile_rejects_bad_values_with_a_readable_message(client):
    response = client.put("/api/profile", json={"diet": "carnivore"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str) and "diet" in response.json()["detail"]


# -------------------------------------------------------------- label scans


def test_label_scan_returns_item_evaluation_harness_and_explanation(client, monkeypatch):
    chat = use_model(monkeypatch, label_reading(), SUMMARY)
    response = client.post("/api/scan/label", files=upload())
    assert response.status_code == 200
    body = response.json()

    assert body["needs_retake"] is False
    assert body["harness"] == {"ok": True, "attempts": 1, "issues": []}
    assert body["item"]["name"] == "Masala Chips"
    assert body["item"]["nutrients"]["calories"] == {"lo": 160, "hi": 160}
    assert body["evaluation"]["overall"] in {"green", "amber", "red"}
    assert body["explanation"] == SUMMARY["summary"]
    assert body["thumbnail"].startswith("data:image/jpeg;base64,")

    # The label call carries the image and the schema at temperature 0 (set in the client).
    messages, schema = chat.calls[0]
    assert "images" in messages[0] and schema["required"][0] == "product_name"
    # The explanation call sees only rule results: no image and no ingredient list.
    explain_messages, explain_schema = chat.calls[1]
    assert "images" not in explain_messages[0]
    assert "sunflower oil" not in explain_messages[0]["content"]
    assert list(explain_schema["properties"]) == ["summary"]


def test_label_scan_retries_after_a_failed_check(client, monkeypatch):
    chat = use_model(monkeypatch, label_reading(calories=60), label_reading(), SUMMARY)
    body = client.post("/api/scan/label", files=upload()).json()
    assert body["harness"]["ok"] is True and body["harness"]["attempts"] == 2
    assert body["item"]["nutrients"]["calories"]["lo"] == 160
    assert "60 kcal" in chat.calls[1][0][-1]["content"]


def test_label_scan_asks_for_a_retake_when_every_attempt_fails(client, monkeypatch):
    use_model(monkeypatch, *[label_reading(calories=60)] * 3)
    body = client.post("/api/scan/label", files=upload()).json()
    assert body["needs_retake"] is True
    assert body["item"] is None and body["evaluation"] is None
    assert body["harness"]["ok"] is False and body["harness"]["attempts"] == 3
    assert body["harness"]["issues"]
    assert "photo" in body["message"]


def test_label_scan_converts_per_100g_kj_and_salt(client, monkeypatch):
    reading = label_reading(basis="per_100g", serving_size_g=50, calories=None, energy_kj=2092,
                            protein_g=8, carbs_g=60, sugar_g=4, fat_g=24, sodium_mg=None, salt_g=1.5)
    use_model(monkeypatch, reading, SUMMARY)
    nutrients = client.post("/api/scan/label", files=upload()).json()["item"]["nutrients"]
    assert nutrients["calories"]["lo"] == pytest.approx(250, abs=0.1)     # 2092 kJ / 4.184 / 2
    assert nutrients["sodium_mg"]["lo"] == pytest.approx(300, abs=0.1)    # 1.5 g x 400 / 2
    assert nutrients["carbs_g"]["lo"] == 30


def test_label_scan_without_serving_size_treats_100g_as_one_serving(client, monkeypatch):
    reading = label_reading(basis="per_100g", serving_size_g=None, calories=520,
                            protein_g=7, carbs_g=55, sugar_g=3, fat_g=30)
    use_model(monkeypatch, reading, SUMMARY)
    scanned = client.post("/api/scan/label", files=upload()).json()["item"]
    assert scanned["serving_size_g"] == 100
    assert scanned["nutrients"]["calories"]["lo"] == 520
    assert any("100 g" in note for note in scanned["notes"])


def test_label_scan_uses_the_saved_profile(client, monkeypatch):
    client.put("/api/profile", json={"allergens": ["milk"]})
    use_model(monkeypatch, label_reading(ingredients=["potato", "milk solids"]), SUMMARY)
    body = client.post("/api/scan/label", files=upload()).json()
    assert body["evaluation"]["overall"] == "red"
    assert body["evaluation"]["disclaimer"]


def test_label_scan_rejects_a_file_that_is_not_an_image(client):
    response = client.post("/api/scan/label", files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 400
    assert "could not be read as an image" in response.json()["detail"]


def test_scan_reports_ollama_down(client, monkeypatch):
    def down():
        raise ollama_client.OllamaError(
            "Cannot reach Ollama at http://127.0.0.1:11434. Start it with ollama serve", 503)
    monkeypatch.setattr(ollama_client, "require_ready", down)
    response = client.post("/api/scan/label", files=upload())
    assert response.status_code == 503
    assert "ollama serve" in response.json()["detail"]


def test_scan_reports_missing_model(client, monkeypatch):
    def missing(messages, schema=None):
        raise ollama_client.OllamaError(
            "Model gemma4:e4b is not installed. Run ollama pull gemma4:e4b", 503)
    monkeypatch.setattr(ollama_client, "chat", missing)
    response = client.post("/api/scan/label", files=upload())
    assert response.status_code == 503
    assert "ollama pull" in response.json()["detail"]


# --------------------------------------------------------------- meal scans


def test_meal_scan_from_description_only(client, monkeypatch):
    chat = use_model(monkeypatch, meal_reading(), SUMMARY)
    response = client.post("/api/scan/meal", data={"description": "dal and rice, home cooked"})
    body = response.json()
    assert response.status_code == 200 and body["needs_retake"] is False
    assert body["item"]["source"] == "meal"
    assert body["item"]["nutrients"]["calories"] == {"lo": 400, "hi": 500}
    assert body["item"]["nutrients"]["sugar_g"] is None
    assert body["item"]["nutrients"]["sodium_mg"] is None
    assert body["thumbnail"] is None

    prompt = chat.calls[0][0][0]
    assert "images" not in prompt
    assert "dal and rice, home cooked" in prompt["content"]


def test_meal_scan_with_photo_and_description(client, monkeypatch):
    chat = use_model(monkeypatch, meal_reading(), SUMMARY)
    body = client.post("/api/scan/meal", files=upload("meal.png"),
                       data={"description": "two rotis"}).json()
    assert body["thumbnail"].startswith("data:image/jpeg")
    assert "images" in chat.calls[0][0][0]


def test_meal_scan_needs_a_photo_or_a_description(client):
    response = client.post("/api/scan/meal", data={"description": "   "})
    assert response.status_code == 400
    assert "photo, a description, or both" in response.json()["detail"]


def test_meal_scan_rejects_a_long_description(client):
    response = client.post("/api/scan/meal", data={"description": "x" * 601})
    assert response.status_code == 400 and "600" in response.json()["detail"]


def test_meal_allergen_warning_without_a_match(client, monkeypatch):
    client.put("/api/profile", json={"allergens": ["peanut"]})
    use_model(monkeypatch, meal_reading(), SUMMARY)
    rules = client.post("/api/scan/meal", data={"description": "dal"}).json()["evaluation"]["rules"]
    peanut = next(r for r in rules if r["id"] == "allergen:peanut")
    assert peanut["status"] == "warn"


# ------------------------------------------------------------- explanation


def test_explanation_falls_back_when_the_model_says_safe(client, monkeypatch):
    use_model(monkeypatch, label_reading(), {"summary": "This food is safe for you."})
    body = client.post("/api/scan/label", files=upload()).json()
    assert "safe" not in body["explanation"].lower()
    assert body["explanation"] == explain.template_summary(body["evaluation"])


def test_explanation_falls_back_when_the_model_call_fails(client, monkeypatch):
    replies = iter([label_reading()])

    def chat(messages, schema=None):
        try:
            return json.dumps(next(replies))
        except StopIteration:
            raise ollama_client.OllamaError("timed out", 504)

    monkeypatch.setattr(ollama_client, "chat", chat)
    body = client.post("/api/scan/label", files=upload()).json()
    assert body["explanation"] == explain.template_summary(body["evaluation"])


# ----------------------------------------------------------------- evaluate


def test_evaluate_rescales_without_calling_the_model(client, monkeypatch):
    chat = use_model(monkeypatch)        # any model call would raise
    response = client.post("/api/evaluate", json={"item": item(), "servings": 2.5})
    body = response.json()
    assert response.status_code == 200
    assert body["evaluation"]["totals"]["calories"] == {"lo": 500, "hi": 500}
    assert body["explanation"] == explain.template_summary(body["evaluation"])
    assert chat.calls == []


def test_evaluate_rejects_zero_servings(client):
    response = client.post("/api/evaluate", json={"item": item(), "servings": 0})
    assert response.status_code == 422 and "servings" in response.json()["detail"]


def test_evaluate_excludes_the_entry_being_edited(client):
    big = item()
    big["nutrients"]["calories"] = {"lo": 1900, "hi": 1900}
    entry = client.post("/api/log", json={"item": big}).json()

    def calorie_status(payload):
        rules = client.post("/api/evaluate", json=payload).json()["evaluation"]["rules"]
        return next(r for r in rules if r["id"] == "calories")

    counted = calorie_status({"item": item()})
    assert "goes over today's goal" in counted["detail"]
    editing = calorie_status({"item": item(), "exclude_log_id": entry["id"]})
    assert "leaves 1800 kcal" in editing["detail"]


# ---------------------------------------------------------------------- log


def test_log_create_list_update_delete(client):
    created = client.post("/api/log", json={
        "item": item(), "servings": 1.5,
        "thumbnail": "data:image/jpeg;base64,AAAA", "explanation": "Looks fine.",
    })
    assert created.status_code == 201
    entry = created.json()
    assert entry["day"] == date.today().isoformat()
    assert entry["kind"] == "label" and entry["calories"] == 300
    assert entry["explanation"] == "Looks fine."
    assert entry["evaluation"]["servings"] == 1.5

    listing = client.get("/api/log").json()
    assert [e["id"] for e in listing["entries"]] == [entry["id"]]
    assert listing["totals"]["calories"] == 300 and listing["totals"]["sugar_g"] == 7.5
    assert listing["targets"]["calories"] == 2000

    renamed = item(name="Renamed")
    updated = client.put(f"/api/log/{entry['id']}", json={"item": renamed, "servings": 2}).json()
    assert updated["name"] == "Renamed" and updated["calories"] == 400
    assert updated["thumbnail"] == "data:image/jpeg;base64,AAAA"

    assert client.delete(f"/api/log/{entry['id']}").json() == {"deleted": entry["id"]}
    assert client.get("/api/log").json()["entries"] == []


def test_log_meal_entry_stores_the_midpoint(client):
    meal = item("meal")
    meal["nutrients"]["calories"] = {"lo": 400, "hi": 600}
    entry = client.post("/api/log", json={"item": meal}).json()
    assert entry["kind"] == "meal" and entry["calories"] == 500
    assert entry["evaluation"]["totals"]["calories"] == {"lo": 400, "hi": 600}


def test_log_unknown_entry_is_404(client):
    assert client.put("/api/log/999", json={"item": item()}).status_code == 404
    assert client.delete("/api/log/999").status_code == 404


def test_log_rejects_bad_day_and_bad_thumbnail(client):
    assert client.get("/api/log?day=yesterday").status_code == 400
    assert client.post("/api/log", json={"item": item(), "day": "3 Oct"}).status_code == 422
    assert client.post("/api/log", json={"item": item(), "thumbnail": "http://x/y.jpg"}).status_code == 422


def test_log_by_day(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client.post("/api/log", json={"item": item(), "day": yesterday})
    assert client.get("/api/log").json()["entries"] == []
    assert len(client.get(f"/api/log?day={yesterday}").json()["entries"]) == 1


# --------------------------------------------------------------------- week


def test_week_has_seven_days_from_sunday_with_status_and_streak(client):
    today = date.today()
    over = item()
    over["nutrients"]["calories"] = {"lo": 2500, "hi": 2500}
    client.post("/api/log", json={"item": item()})
    client.post("/api/log", json={"item": over, "day": (today - timedelta(days=1)).isoformat()})

    week = client.get("/api/week").json()
    days = week["days"]
    assert len(days) == 7 and days[0]["weekday"] == "Sun" and days[6]["weekday"] == "Sat"
    assert week["streak"] == 2

    by_day = {d["day"]: d for d in days}
    assert by_day[today.isoformat()]["is_today"] is True
    assert by_day[today.isoformat()]["status"] == "on"
    assert by_day[today.isoformat()]["totals"]["calories"] == 200
    yesterday = (today - timedelta(days=1)).isoformat()
    if yesterday in by_day:                      # yesterday may fall in the previous week
        assert by_day[yesterday]["status"] == "off"
    assert sum(d["status"] == "none" for d in days) >= 5


def test_week_streak_is_zero_with_an_empty_log(client):
    week = client.get("/api/week").json()
    assert week["streak"] == 0
    assert all(d["status"] == "none" for d in week["days"])


def test_streak_survives_an_empty_today(client):
    today = date.today()
    for back in (1, 2, 3):
        client.post("/api/log", json={"item": item(), "day": (today - timedelta(days=back)).isoformat()})
    assert client.get("/api/week").json()["streak"] == 3


# ------------------------------------------------------------------- static


def test_static_app_is_served_at_the_root(client):
    response = client.get("/")
    assert response.status_code == 200 and "My Thali" in response.text


def test_image_is_resized_and_reencoded_as_jpeg():
    from io import BytesIO

    from PIL import Image

    jpeg = extract.prepare_image(png_bytes((4000, 2000)))
    image = Image.open(BytesIO(jpeg))
    assert image.format == "JPEG" and max(image.size) == 1600
