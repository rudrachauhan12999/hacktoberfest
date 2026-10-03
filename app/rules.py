"""The rule engine: decides how a food fits the user's goals.

Pure Python, no model. Every decision here is arithmetic on ranges or a
lookup in the knowledge tables, so the same input always gives the same
verdict and each verdict can be traced to a rule.

    evaluate(item, servings, profile, consumed) -> {
        "servings": 1.5,
        "totals":   {"calories": {"lo": 240, "hi": 240}, "sugar_g": None, ...},
        "rules":    [{"id", "label", "status", "detail"}, ...],
        "overall":  "green" | "amber" | "red",
        "notes":    [...],
        "disclaimer": str | None,
    }
"""

from __future__ import annotations

from typing import Optional

from .knowledge import DIET_LABELS, DIET_NOTES, Hit, find_diet_conflict, normalise, resolve_allergen
from .schemas import NUTRIENT_KEYS, Profile

PASS, WARN, FAIL = "pass", "warn", "fail"
_SEVERITY = {PASS: 0, WARN: 1, FAIL: 2}
_OVERALL = {PASS: "green", WARN: "amber", FAIL: "red"}

WARN_FRACTION = 0.8

ALLERGEN_DISCLAIMER = (
    "Allergen checks flag risk from the printed ingredients. "
    "They do not certify food as safe."
)
INGREDIENTS_NOT_READ = "Ingredients not read, so allergens were not checked"
MEAL_ALLERGEN_WARNING = "Estimated from a photo. Hidden ingredients cannot be seen."


def _worst(*statuses: str) -> str:
    return max(statuses, key=_SEVERITY.__getitem__)


def _num(value: float) -> str:
    """Format an amount: whole numbers from 10 up, one decimal below."""
    rounded = round(value) if abs(value) >= 10 else round(value, 1)
    return f"{rounded:g}"


def _amount(rng: dict, unit: str) -> str:
    if _num(rng["lo"]) == _num(rng["hi"]):
        return f"{_num(rng['lo'])} {unit}"
    return f"{_num(rng['lo'])} to {_num(rng['hi'])} {unit}"


def _rule(rule_id: str, label: str, status: str, detail: str) -> dict:
    return {"id": rule_id, "label": label, "status": status, "detail": detail}


def scale(nutrients: dict, servings: float) -> dict:
    """Multiply every known nutrient range by the number of servings."""
    totals: dict[str, Optional[dict]] = {}
    for key in NUTRIENT_KEYS:
        rng = nutrients.get(key)
        if rng is None:
            totals[key] = None
        else:
            totals[key] = {
                "lo": round(rng["lo"] * servings, 1),
                "hi": round(rng["hi"] * servings, 1),
            }
    return totals


# ---------------------------------------------------------- nutrient rules


def _max_rule(rule_id: str, label: str, rng: Optional[dict], limit: Optional[float],
              unit: str) -> Optional[dict]:
    """A nutrient with an upper limit per meal. Skipped when either side is unknown."""
    if rng is None or limit is None:
        return None
    amount, cap = _amount(rng, unit), f"{_num(limit)} {unit}"
    if rng["lo"] > limit:
        return _rule(rule_id, label, FAIL, f"{amount} is over your per-meal limit of {cap}.")
    if rng["hi"] > limit:
        return _rule(rule_id, label, WARN, f"{amount} may exceed your per-meal limit of {cap}.")
    if rng["hi"] > WARN_FRACTION * limit:
        return _rule(rule_id, label, WARN, f"{amount} is close to your limit of {cap} per meal.")
    return _rule(rule_id, label, PASS, f"{amount} is within your per-meal limit of {cap}.")


def _calorie_rule(rng: Optional[dict], profile: Profile, consumed: float) -> Optional[dict]:
    """The per-meal limit, plus a check against what is left of today's goal."""
    daily = profile.calories
    rule = _max_rule("calories", "Calories", rng, profile.per_meal(daily), "kcal")
    if rule is None or rng is None or daily is None:
        return rule

    goal = f"{_num(daily)} kcal"
    if consumed + rng["lo"] > daily:
        over = consumed + rng["lo"] - daily
        rule["status"] = FAIL
        rule["detail"] += f" It goes over today's goal of {goal} by {_num(over)} kcal."
    elif consumed + rng["hi"] > daily:
        rule["status"] = _worst(rule["status"], WARN)
        rule["detail"] += f" It may go over today's goal of {goal}."
    else:
        left = daily - consumed - (rng["lo"] + rng["hi"]) / 2
        about = "" if rng["lo"] == rng["hi"] else "about "
        rule["detail"] += f" It leaves {about}{_num(left)} kcal for the rest of today."
    return rule


def _protein_rule(rng: Optional[dict], target: Optional[float]) -> Optional[dict]:
    """Protein is a minimum. Falling short is a warning, never a failure."""
    if rng is None or target is None:
        return None
    amount, goal = _amount(rng, "g"), f"{_num(target)} g"
    if rng["lo"] >= target:
        return _rule("protein", "Protein", PASS, f"{amount} meets your per-meal target of {goal}.")
    covered = round(100 * rng["lo"] / target)
    return _rule(
        "protein", "Protein", WARN,
        f"{amount} covers about {covered}% of your per-meal target of {goal}.",
    )


# ------------------------------------------------------- ingredient rules


def _found(hit: Hit) -> str:
    """Describe a match: the term, and the ingredient it sits in when that adds detail."""
    if normalise(hit.source) == hit.term:
        return f'"{hit.term}"'
    return f'"{hit.term}" in "{hit.source}"'


def _allergen_rule(typed: str, item: dict, source: str) -> dict:
    rule_id, label = f"allergen:{normalise(typed)}", f"Allergen: {typed}"
    groups = resolve_allergen(typed)
    declared = [*item.get("ingredients", []), *item.get("contains", [])]
    if source == "meal":
        declared += [item.get("name", ""), *[part.get("name", "") for part in item.get("items", [])]]

    for group in groups:
        hit = group.find(declared)
        if hit:
            return _rule(rule_id, label, FAIL, f"Contains {group.label}: found {_found(hit)}.")

    if source == "meal":
        return _rule(rule_id, label, WARN, MEAL_ALLERGEN_WARNING)

    for group in groups:
        hit = group.find(item.get("may_contain", []))
        if hit:
            return _rule(rule_id, label, WARN, f"May contain {group.label}: the label says {_found(hit)}.")

    if not item.get("ingredients"):
        return _rule(rule_id, label, WARN, INGREDIENTS_NOT_READ)
    return _rule(rule_id, label, PASS, f"No {typed} found in the printed ingredients.")


def _diet_rule(diet: str, item: dict, source: str) -> Optional[dict]:
    if diet == "none":
        return None
    label = DIET_LABELS[diet]
    declared = [*item.get("ingredients", []), *item.get("contains", [])]
    if source == "meal":
        declared += [item.get("name", ""), *[part.get("name", "") for part in item.get("items", [])]]

    conflict = find_diet_conflict(diet, declared)
    if conflict:
        group, hit = conflict
        return _rule("diet", f"Diet: {label}", FAIL, f"Not {label.lower()}: found {_found(hit)} ({group.label}).")
    if source == "label" and not item.get("ingredients"):
        return _rule("diet", f"Diet: {label}", WARN, "Ingredients not read, so the diet was not checked.")
    where = "the likely ingredients" if source == "meal" else "the printed ingredients"
    return _rule("diet", f"Diet: {label}", PASS, f"Nothing in {where} conflicts with a {label.lower()} diet.")


# ---------------------------------------------------------------- evaluate


def evaluate(item: dict, servings: float, profile: Profile,
             consumed: Optional[dict] = None, source: Optional[str] = None) -> dict:
    """Judge an item against the profile.

    item      a normalised item (one serving, nutrients as ranges)
    servings  how many servings are eaten
    consumed  calories and macros already logged today, without this item
    source    "label" or "meal"; defaults to the item's own source
    """
    source = source or item.get("source", "label")
    consumed = consumed or {}
    totals = scale(item.get("nutrients", {}), servings)
    per_meal = profile.per_meal

    candidates = [
        _calorie_rule(totals["calories"], profile, float(consumed.get("calories") or 0.0)),
        _protein_rule(totals["protein_g"], per_meal(profile.protein_g)),
        _max_rule("carbs", "Carbs", totals["carbs_g"], per_meal(profile.carbs_g), "g"),
        _max_rule("fat", "Fat", totals["fat_g"], per_meal(profile.fat_g), "g"),
        _max_rule("sugar", "Sugar", totals["sugar_g"], per_meal(profile.sugar_g_max), "g"),
        _max_rule("sodium", "Sodium", totals["sodium_mg"], per_meal(profile.sodium_mg_max), "mg"),
        *[_allergen_rule(allergen, item, source) for allergen in profile.allergens],
        _diet_rule(profile.diet, item, source),
    ]
    rules = [rule for rule in candidates if rule is not None]
    worst = _worst(PASS, *[rule["status"] for rule in rules])

    notes = []
    if profile.diet in DIET_NOTES:
        notes.append(DIET_NOTES[profile.diet])

    return {
        "servings": servings,
        "totals": totals,
        "rules": rules,
        "overall": _OVERALL[worst],
        "notes": notes,
        "disclaimer": ALLERGEN_DISCLAIMER if profile.allergens else None,
    }
