"""Reading a photo: image preparation, prompts, and normalisation.

    photo -> prepare_image -> model (through the harness) -> normalise

The model's answer describes what is printed or what it estimates. The
normalise functions turn that into the app's item: one serving, every
nutrient a {lo, hi} range, unit conversions done in Python.
"""

from __future__ import annotations

import base64
import io
from typing import Optional

from PIL import Image, ImageOps

from . import harness
from .config import JPEG_QUALITY, MAX_IMAGE_SIDE, THUMBNAIL_SIDE, settings
from .ollama_client import user_message
from .schemas import LABEL_SCHEMA, MEAL_RANGE_FIELDS, MEAL_SCHEMA
from .verify import label_calories, label_sodium_mg, number, verify_label, verify_meal


class ImageError(ValueError):
    """The upload could not be opened as an image."""


# ------------------------------------------------------------------- images


def _to_jpeg(image: Image.Image, longest_side: int, quality: int) -> bytes:
    image = image.copy()
    image.thumbnail((longest_side, longest_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def prepare_image(raw: bytes) -> bytes:
    """Fix EXIF rotation, shrink the longest side to 1600 px, and encode as JPEG."""
    try:
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        return _to_jpeg(image, MAX_IMAGE_SIDE, JPEG_QUALITY)
    except Exception as exc:
        raise ImageError(
            "That file could not be read as an image. Use a JPEG, PNG or WebP photo."
        ) from exc


def make_thumbnail(jpeg: bytes) -> str:
    """A small JPEG data URL of a prepared image, stored with the log entry."""
    image = Image.open(io.BytesIO(jpeg))
    small = _to_jpeg(image, THUMBNAIL_SIDE, 80)
    return "data:image/jpeg;base64," + base64.b64encode(small).decode("ascii")


# ------------------------------------------------------------------- labels

LABEL_PROMPT = """\
You are reading the nutrition label of a packaged food from a photo.
Report only what is printed. Reply with JSON.

Rules:
- Copy printed numbers exactly, digit for digit.
- Never calculate or estimate a value. If a value is not printed or cannot be read, use null.
- If the table has both a per-serving column and a per-100 g column, read the per-serving
  column and set basis to "per_serving". If it has only a per-100 g (or per-100 ml) column,
  set basis to "per_100g".
- serving_size_g is the printed serving size in grams (or millilitres), or null.
- calories is energy in kcal. If energy is printed only in kJ, leave calories null and
  put the kJ number in energy_kj.
- sodium_mg is sodium in milligrams. If only salt is printed, leave sodium_mg null and
  put the salt amount in grams in salt_g.
- carbs_g is total carbohydrate. sugar_g is total sugars. fat_g is total fat.
- ingredients: every ingredient in the printed list, in order, as English strings.
  Translate Hindi and Gujarati into English. Split compound ingredients into their parts,
  for example "chocolate (sugar, cocoa butter, milk solids)" becomes
  "sugar", "cocoa butter", "milk solids". Use an empty list if no ingredient list is visible.
- contains: allergens named in a "Contains" statement, in English.
- may_contain: allergens named in a "May contain" or "traces of" statement, in English.
- product_name is the product name if visible, otherwise null.
"""

LABEL_RETRY_HINT = (
    "Look at the image again and re-read the values you got wrong. "
    "Copy what is printed. Do not change a number only to make the arithmetic work, "
    "and use null for anything that is not printed."
)


def read_label(jpeg: bytes) -> harness.HarnessResult:
    """Ask the model to read a label photo, verifying and retrying as needed."""
    return harness.run(
        [user_message(LABEL_PROMPT, jpeg)],
        LABEL_SCHEMA,
        verify_label,
        max_retries=settings.max_retries,
        retry_hint=LABEL_RETRY_HINT,
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text.strip() for text in value if isinstance(text, str) and text.strip()]


def normalise_label(data: dict) -> dict:
    """Convert a verified label reading into an item for one serving."""
    notes: list[str] = []
    basis = data.get("basis") if data.get("basis") in ("per_serving", "per_100g") else "per_serving"
    serving = number(data, "serving_size_g")
    if serving is not None and serving <= 0:
        serving = None

    factor = 1.0
    if basis == "per_100g":
        if serving is None:
            serving = 100.0
            notes.append("No serving size printed, so one serving is treated as 100 g.")
        else:
            factor = serving / 100.0
            notes.append(f"The label gives values per 100 g. They are scaled to one {serving:g} g serving.")

    if number(data, "calories") is None and number(data, "energy_kj") is not None:
        notes.append("Calories are converted from the printed kJ value.")
    if number(data, "sodium_mg") is None and number(data, "salt_g") is not None:
        notes.append("Sodium is converted from the printed salt value.")

    values = {
        "calories": label_calories(data),
        "protein_g": number(data, "protein_g"),
        "carbs_g": number(data, "carbs_g"),
        "sugar_g": number(data, "sugar_g"),
        "fat_g": number(data, "fat_g"),
        "fiber_g": number(data, "fiber_g"),
        "sodium_mg": label_sodium_mg(data),
    }
    nutrients = {}
    for key, value in values.items():
        if value is None:
            nutrients[key] = None
        else:
            amount = round(value * factor, 1)
            nutrients[key] = {"lo": amount, "hi": amount}

    name = data.get("product_name")
    return {
        "source": "label",
        "name": name.strip() if isinstance(name, str) and name.strip() else "Packaged food",
        "basis": basis,
        "serving_size_g": serving,
        "nutrients": nutrients,
        "ingredients": _strings(data.get("ingredients")),
        "contains": _strings(data.get("contains")),
        "may_contain": _strings(data.get("may_contain")),
        "items": [],
        "notes": notes,
    }


# -------------------------------------------------------------------- meals

MEAL_PROMPT = """\
You are estimating the nutrition of one meal as served to one person. Reply with JSON.

Rules:
- Use exactly these keys: dish_name, items, calories_min, calories_max, protein_g_min,
  protein_g_max, carbs_g_min, carbs_g_max, fat_g_min, fat_g_max, likely_ingredients.
- dish_name: a short English name for the meal.
- items: each food in the meal as an object {"name": ..., "portion": ...}, with an
  estimated portion such as "2 pieces" or "1 cup".
- Give every nutrient as a range: the _min and _max keys are numbers, calories in kcal
  and the others in grams.
- Widen the range when the portion size or the amount of oil, ghee or butter is uncertain.
- Keep calories consistent with the macros: about 4 kcal per gram of protein,
  4 per gram of carbohydrate and 9 per gram of fat.
- likely_ingredients: English names of the ingredients the dish normally contains,
  including the oil, dairy, nuts and flour used in cooking even when they cannot be seen.
- If the user describes the dish, trust the description over what the photo seems to show.
"""

MEAL_RETRY_HINT = "Revise the estimate so that the ranges are consistent with each other."


def meal_messages(jpeg: Optional[bytes], description: str) -> list[dict]:
    parts = [MEAL_PROMPT]
    if description:
        parts.append(f'The user describes the dish as: "{description}"')
    if jpeg is None:
        parts.append("There is no photo. Estimate from the description alone.")
    return [user_message("\n".join(parts), jpeg)]


def read_meal(jpeg: Optional[bytes], description: str) -> harness.HarnessResult:
    """Ask the model to estimate a meal from a photo, a description, or both."""
    return harness.run(
        meal_messages(jpeg, description),
        MEAL_SCHEMA,
        verify_meal,
        max_retries=settings.max_retries,
        retry_hint=MEAL_RETRY_HINT,
    )


def normalise_meal(data: dict, has_photo: bool = True) -> dict:
    """Convert a verified meal estimate into an item. Sugar and sodium stay unknown."""
    nutrients: dict[str, Optional[dict]] = {
        "sugar_g": None, "fiber_g": None, "sodium_mg": None,
    }
    for field in MEAL_RANGE_FIELDS:
        nutrients[field] = {
            "lo": round(number(data, f"{field}_min") or 0.0, 1),
            "hi": round(number(data, f"{field}_max") or 0.0, 1),
        }

    parts = []
    for part in data.get("items") or []:
        if isinstance(part, str) and part.strip():
            parts.append({"name": part.strip()[:160], "portion": ""})
        elif isinstance(part, dict) and isinstance(part.get("name"), str) and part["name"].strip():
            portion = part.get("portion")
            parts.append({
                "name": part["name"].strip()[:160],
                "portion": portion.strip()[:160] if isinstance(portion, str) else "",
            })

    name = data.get("dish_name")
    how = "a photo" if has_photo else "your description"
    return {
        "source": "meal",
        "name": name.strip() if isinstance(name, str) and name.strip() else "Meal",
        "basis": None,
        "serving_size_g": None,
        "nutrients": nutrients,
        "ingredients": _strings(data.get("likely_ingredients")),
        "contains": [],
        "may_contain": [],
        "items": parts,
        "notes": [
            f"These values are estimated from {how} and shown as ranges.",
            "Sugar and sodium are not estimated for meals.",
        ],
    }
