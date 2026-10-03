"""Verifiers: plain arithmetic checks on what the model read or estimated.

Each verifier takes the model's parsed JSON and returns a list of error
messages. An empty list means the answer is acceptable. Every message
states the numbers involved, because the harness sends the messages back to
the model as a correction request.

The checks rest on facts the model cannot argue with: 100 g of food cannot
hold more than 100 g of macronutrients, sugar is part of carbohydrate, and
energy follows from the macros at 4, 4 and 9 kcal per gram.
"""

from __future__ import annotations

from typing import Optional

from .schemas import LABEL_NUMERIC_FIELDS, MEAL_RANGE_FIELDS

KJ_PER_KCAL = 4.184
SODIUM_MG_PER_SALT_G = 400

_LABEL_NUTRIENT_FIELDS = tuple(f for f in LABEL_NUMERIC_FIELDS if f != "serving_size_g")

_NAMES = {
    "serving_size_g": "serving size",
    "calories": "calories",
    "energy_kj": "energy in kJ",
    "protein_g": "protein",
    "carbs_g": "carbohydrate",
    "sugar_g": "sugar",
    "fat_g": "fat",
    "fiber_g": "fiber",
    "sodium_mg": "sodium",
    "salt_g": "salt",
}


def number(data: dict, key: str) -> Optional[float]:
    """Read a numeric field, treating anything that is not a number as missing."""
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def label_calories(data: dict) -> Optional[float]:
    """Calories as printed, or converted from kJ when only kJ is printed."""
    calories = number(data, "calories")
    if calories is not None:
        return calories
    energy_kj = number(data, "energy_kj")
    return None if energy_kj is None else energy_kj / KJ_PER_KCAL


def label_sodium_mg(data: dict) -> Optional[float]:
    """Sodium as printed, or converted from salt when only salt is printed."""
    sodium = number(data, "sodium_mg")
    if sodium is not None:
        return sodium
    salt = number(data, "salt_g")
    return None if salt is None else salt * SODIUM_MG_PER_SALT_G


def macro_calories(protein: float, carbs: float, fat: float) -> float:
    return 4 * protein + 4 * carbs + 9 * fat


def verify_label(data: dict) -> list[str]:
    errors: list[str] = []

    if all(number(data, field) is None for field in _LABEL_NUTRIENT_FIELDS):
        return ["No nutrition values were read. Every nutrient field is null."]

    for field in LABEL_NUMERIC_FIELDS:
        value = number(data, field)
        if value is not None and value < 0:
            errors.append(f"{_NAMES[field]} is {value:g}, and a label value cannot be negative.")

    basis = data.get("basis")
    serving = number(data, "serving_size_g")
    protein = number(data, "protein_g")
    carbs = number(data, "carbs_g")
    fat = number(data, "fat_g")
    sugar = number(data, "sugar_g")
    calories = label_calories(data)
    sodium = label_sodium_mg(data)
    macro_sum = (protein or 0) + (carbs or 0) + (fat or 0)

    if basis == "per_100g" and macro_sum > 100.5:
        errors.append(
            f"protein {protein or 0:g} g + carbohydrate {carbs or 0:g} g + fat {fat or 0:g} g "
            f"= {macro_sum:g} g, which is more than the 100 g the column describes."
        )
    if basis == "per_serving" and serving is not None and serving > 0 and macro_sum > serving * 1.05:
        errors.append(
            f"protein {protein or 0:g} g + carbohydrate {carbs or 0:g} g + fat {fat or 0:g} g "
            f"= {macro_sum:g} g, which is more than the serving size of {serving:g} g."
        )

    if sugar is not None and carbs is not None and sugar > carbs + 0.5:
        errors.append(
            f"sugar is {sugar:g} g but carbohydrate is only {carbs:g} g. "
            "Sugar is part of carbohydrate and cannot be larger."
        )

    if calories is not None:
        if basis == "per_100g" and calories > 905:
            errors.append(
                f"calories are {calories:.0f} kcal per 100 g. "
                "Pure fat is about 900 kcal per 100 g, so nothing can be higher."
            )
        if calories > 3000:
            errors.append(
                f"calories are {calories:.0f} kcal, which is more than 3000 kcal "
                "and too high for one serving or 100 g."
            )
        if protein is not None and carbs is not None and fat is not None:
            expected = macro_calories(protein, carbs, fat)
            allowed = max(25.0, 0.20 * calories)
            if abs(calories - expected) > allowed:
                errors.append(
                    f"calories are {calories:.0f} kcal, but protein {protein:g} g, "
                    f"carbohydrate {carbs:g} g and fat {fat:g} g give about {expected:.0f} kcal "
                    "(4, 4 and 9 kcal per gram). One of these values was misread."
                )

    if sodium is not None and sodium > 10000:
        errors.append(
            f"sodium is {sodium:.0f} mg, which is more than 10000 mg. "
            "Check the unit: the label may print grams, or salt rather than sodium."
        )

    return errors


def verify_meal(data: dict) -> list[str]:
    errors: list[str] = []

    items = data.get("items")
    if not isinstance(items, list) or not items:
        errors.append("The items list is empty. List each food visible or described.")

    midpoints: dict[str, float] = {}
    for field in MEAL_RANGE_FIELDS:
        low = number(data, f"{field}_min")
        high = number(data, f"{field}_max")
        name = _NAMES[field]
        if low is None or high is None:
            errors.append(f"{name} needs both a minimum and a maximum number.")
            continue
        if low < 0 or high < 0:
            errors.append(f"{name} range is {low:g} to {high:g}, and an amount cannot be negative.")
        if low > high:
            errors.append(f"{name} minimum {low:g} is greater than its maximum {high:g}.")
        midpoints[field] = (low + high) / 2

    calories = midpoints.get("calories")
    if calories is not None:
        if calories > 3500:
            errors.append(
                f"the calorie estimate is centred on {calories:.0f} kcal, "
                "which is more than 3500 kcal and too high for one meal."
            )
        if len(midpoints) == len(MEAL_RANGE_FIELDS):
            expected = macro_calories(
                midpoints["protein_g"], midpoints["carbs_g"], midpoints["fat_g"]
            )
            allowed = max(60.0, 0.25 * calories)
            if abs(calories - expected) > allowed:
                errors.append(
                    f"the calorie estimate is centred on {calories:.0f} kcal, but the middle of "
                    f"the macro ranges (protein {midpoints['protein_g']:g} g, carbohydrate "
                    f"{midpoints['carbs_g']:g} g, fat {midpoints['fat_g']:g} g) gives about "
                    f"{expected:.0f} kcal. Make the calories and macros agree."
                )

    return errors
