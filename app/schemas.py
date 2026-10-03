"""Data shapes used across the app.

Two kinds live here:

  * JSON schemas handed to Ollama's "format" field. They constrain what the
    model may emit (constrained decoding), so they describe the model's raw
    reading, before any conversion.
  * Pydantic models for the API. They describe the normalised item (one
    serving, every nutrient a {lo, hi} range) and the request bodies.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ------------------------------------------------- schemas given to the model

_NUMBER_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_STRING_OR_NULL = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}

LABEL_NUMERIC_FIELDS = (
    "serving_size_g", "calories", "energy_kj", "protein_g", "carbs_g",
    "sugar_g", "fat_g", "fiber_g", "sodium_mg", "salt_g",
)

LABEL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "product_name": _STRING_OR_NULL,
        "basis": {"type": "string", "enum": ["per_serving", "per_100g"]},
        **{field: _NUMBER_OR_NULL for field in LABEL_NUMERIC_FIELDS},
        "ingredients": _STRING_LIST,
        "contains": _STRING_LIST,
        "may_contain": _STRING_LIST,
    },
    "required": [
        "product_name", "basis", *LABEL_NUMERIC_FIELDS,
        "ingredients", "contains", "may_contain",
    ],
}

MEAL_RANGE_FIELDS = ("calories", "protein_g", "carbs_g", "fat_g")

MEAL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "dish_name": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "portion": {"type": "string"},
                },
                "required": ["name", "portion"],
            },
        },
        **{
            f"{field}_{bound}": {"type": "number"}
            for field in MEAL_RANGE_FIELDS
            for bound in ("min", "max")
        },
        "likely_ingredients": _STRING_LIST,
    },
    "required": [
        "dish_name", "items",
        *[f"{field}_{bound}" for field in MEAL_RANGE_FIELDS for bound in ("min", "max")],
        "likely_ingredients",
    ],
}

EXPLANATION_SCHEMA: dict = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}

# ------------------------------------------------------------ normalised item

NUTRIENT_KEYS = (
    "calories", "protein_g", "carbs_g", "sugar_g", "fat_g", "fiber_g", "sodium_mg",
)

Goal = Literal["lose_fat", "maintain", "build_muscle"]
Diet = Literal["none", "vegetarian", "eggetarian", "vegan", "jain", "halal"]
Source = Literal["label", "meal"]

_MAX_LIST_ITEMS = 80
_MAX_TEXT = 160


def _clean_strings(values: object) -> list[str]:
    """Trim, drop blanks and duplicates, and cap the length of a string list."""
    if not isinstance(values, (list, tuple)):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        text = " ".join(value.split())[:_MAX_TEXT]
        if text and text.lower() not in seen:
            seen.add(text.lower())
            cleaned.append(text)
    return cleaned[:_MAX_LIST_ITEMS]


class Range(BaseModel):
    """A nutrient amount. A label reading has lo equal to hi."""

    lo: float = Field(ge=0, le=1_000_000)
    hi: float = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def _ordered(self) -> "Range":
        if self.lo > self.hi:
            self.lo, self.hi = self.hi, self.lo
        return self


class Nutrients(BaseModel):
    """Amounts for one serving. None means the value is not known."""

    calories: Optional[Range] = None
    protein_g: Optional[Range] = None
    carbs_g: Optional[Range] = None
    sugar_g: Optional[Range] = None
    fat_g: Optional[Range] = None
    fiber_g: Optional[Range] = None
    sodium_mg: Optional[Range] = None


class MealPart(BaseModel):
    name: str = Field(max_length=_MAX_TEXT)
    portion: str = Field(default="", max_length=_MAX_TEXT)


class Item(BaseModel):
    """A scanned food, normalised to one serving."""

    source: Source
    name: str = Field(default="Unnamed food", max_length=_MAX_TEXT)
    basis: Optional[Literal["per_serving", "per_100g"]] = None
    serving_size_g: Optional[float] = Field(default=None, gt=0, le=10_000)
    nutrients: Nutrients = Field(default_factory=Nutrients)
    ingredients: list[str] = Field(default_factory=list)
    contains: list[str] = Field(default_factory=list)
    may_contain: list[str] = Field(default_factory=list)
    items: list[MealPart] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    notes: list[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        text = " ".join(str(value or "").split())
        return text or "Unnamed food"

    @field_validator("ingredients", "contains", "may_contain", "notes", mode="before")
    @classmethod
    def _lists(cls, value: object) -> list[str]:
        return _clean_strings(value)


# -------------------------------------------------------------------- profile


class Profile(BaseModel):
    """Dietary goals and restrictions. An empty target switches its rule off."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", max_length=80)
    goal: Goal = "maintain"
    diet: Diet = "none"
    allergens: list[str] = Field(default_factory=list)
    meals_per_day: int = Field(default=3, ge=1, le=12)
    calories: Optional[float] = Field(default=2000, gt=0, le=20_000)
    protein_g: Optional[float] = Field(default=75, gt=0, le=1_000)
    carbs_g: Optional[float] = Field(default=250, gt=0, le=2_000)
    fat_g: Optional[float] = Field(default=65, gt=0, le=1_000)
    sugar_g_max: Optional[float] = Field(default=50, gt=0, le=1_000)
    sodium_mg_max: Optional[float] = Field(default=2300, gt=0, le=50_000)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        return " ".join(str(value or "").split())

    @field_validator("allergens", mode="before")
    @classmethod
    def _allergens(cls, value: object) -> list[str]:
        if isinstance(value, str):
            value = re.split(r"[,;\n]", value)
        return _clean_strings(value)[:30]

    def per_meal(self, daily: Optional[float]) -> Optional[float]:
        """The share of a daily target that one meal may use."""
        return None if daily is None else daily / self.meals_per_day


class ProfileOut(Profile):
    configured: bool = False


# ------------------------------------------------------------- request bodies

_THUMBNAIL = re.compile(r"^data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+$")
_MAX_THUMBNAIL_CHARS = 400_000


def _check_day(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("day must look like YYYY-MM-DD") from exc


class EvaluateRequest(BaseModel):
    item: Item
    servings: float = Field(default=1, ge=0.5, le=50)
    exclude_log_id: Optional[int] = None


class LogCreate(BaseModel):
    item: Item
    servings: float = Field(default=1, ge=0.5, le=50)
    day: Optional[str] = None
    thumbnail: Optional[str] = Field(default=None, max_length=_MAX_THUMBNAIL_CHARS)
    explanation: Optional[str] = Field(default=None, max_length=1_000)

    @field_validator("day")
    @classmethod
    def _day(cls, value: Optional[str]) -> Optional[str]:
        return _check_day(value)

    @field_validator("thumbnail")
    @classmethod
    def _thumbnail(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        if not _THUMBNAIL.match(value):
            raise ValueError("thumbnail must be a base64 image data URL")
        return value


class LogUpdate(BaseModel):
    item: Item
    servings: float = Field(default=1, ge=0.5, le=50)
    explanation: Optional[str] = Field(default=None, max_length=1_000)
