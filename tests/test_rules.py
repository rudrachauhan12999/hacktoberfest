"""The rule engine: pass, warn and fail paths for every rule.

The default profile gives per-meal budgets of 667 kcal, 25 g protein,
83 g carbs, 22 g fat, 17 g sugar and 767 mg sodium (daily targets over 3 meals).
"""

import pytest

from app.rules import (
    ALLERGEN_DISCLAIMER, INGREDIENTS_NOT_READ, MEAL_ALLERGEN_WARNING, evaluate,
)
from app.schemas import Profile

from .conftest import item


def exact(value):
    return {"lo": value, "hi": value}


def with_nutrient(key, value, source="label"):
    food = item(source)
    food["nutrients"][key] = value
    return food


def rule(evaluation: dict, rule_id: str) -> dict:
    matches = [r for r in evaluation["rules"] if r["id"] == rule_id]
    assert len(matches) == 1, f"expected one {rule_id} rule, got {evaluation['rules']}"
    return matches[0]


def rule_ids(evaluation: dict) -> list[str]:
    return [r["id"] for r in evaluation["rules"]]


# ------------------------------------------------------------------ overall


def test_everything_within_budget_is_green():
    result = evaluate(item(), 1, Profile())
    assert result["overall"] == "green"
    assert rule_ids(result) == ["calories", "protein", "carbs", "fat", "sugar", "sodium"]
    assert all(r["status"] == "pass" for r in result["rules"])
    assert result["disclaimer"] is None


def test_any_warning_is_amber_and_any_failure_is_red():
    assert evaluate(with_nutrient("protein_g", exact(5)), 1, Profile())["overall"] == "amber"
    assert evaluate(with_nutrient("fat_g", exact(40)), 1, Profile())["overall"] == "red"


def test_servings_scale_every_nutrient():
    result = evaluate(item(), 4, Profile())
    assert result["servings"] == 4
    assert result["totals"]["calories"] == exact(800)
    assert result["totals"]["sodium_mg"] == exact(400)
    assert rule(result, "calories")["status"] == "fail"


def test_unknown_nutrient_or_empty_target_skips_the_rule():
    assert "sugar" not in rule_ids(evaluate(with_nutrient("sugar_g", None), 1, Profile()))
    assert "sugar" not in rule_ids(evaluate(item(), 1, Profile(sugar_g_max=None)))
    assert "calories" not in rule_ids(evaluate(item(), 1, Profile(calories=None)))
    assert "protein" not in rule_ids(evaluate(item(), 1, Profile(protein_g=None)))


# ------------------------------------------------------------ maximum rules


@pytest.mark.parametrize("rule_id, key, passing, close, over", [
    ("carbs", "carbs_g", 50, 70, 90),          # limit 83.3 g, warns above 66.7 g
    ("fat", "fat_g", 10, 20, 30),              # limit 21.7 g, warns above 17.3 g
    ("sugar", "sugar_g", 5, 15, 20),           # limit 16.7 g, warns above 13.3 g
    ("sodium", "sodium_mg", 300, 700, 900),    # limit 767 mg, warns above 613 mg
    ("calories", "calories", 300, 600, 700),   # limit 667 kcal, warns above 533 kcal
])
def test_maximum_rule_pass_warn_fail(rule_id, key, passing, close, over):
    profile = Profile()
    ok = rule(evaluate(with_nutrient(key, exact(passing)), 1, profile), rule_id)
    warn = rule(evaluate(with_nutrient(key, exact(close)), 1, profile), rule_id)
    fail = rule(evaluate(with_nutrient(key, exact(over)), 1, profile), rule_id)

    assert ok["status"] == "pass" and "within" in ok["detail"]
    assert warn["status"] == "warn" and "close to your limit" in warn["detail"]
    assert fail["status"] == "fail" and "over your per-meal limit" in fail["detail"]


def test_range_straddling_the_limit_warns_may_exceed():
    result = evaluate(with_nutrient("carbs_g", {"lo": 70, "hi": 95}, "meal"), 1, Profile())
    carbs = rule(result, "carbs")
    assert carbs["status"] == "warn"
    assert "70 to 95 g may exceed" in carbs["detail"]


def test_range_fails_only_when_its_low_end_is_over():
    result = evaluate(with_nutrient("carbs_g", {"lo": 90, "hi": 120}, "meal"), 1, Profile())
    assert rule(result, "carbs")["status"] == "fail"


# ----------------------------------------------------------------- calories


def test_calories_detail_says_what_is_left_today():
    result = evaluate(item(), 1, Profile(), consumed={"calories": 500})
    calories = rule(result, "calories")
    assert calories["status"] == "pass"
    assert "leaves 1300 kcal for the rest of today" in calories["detail"]


def test_calories_fail_when_the_day_goes_over():
    result = evaluate(item(), 1, Profile(), consumed={"calories": 1900})
    calories = rule(result, "calories")
    assert calories["status"] == "fail"
    assert "goes over today's goal" in calories["detail"]
    assert "by 100 kcal" in calories["detail"]


def test_calories_warn_when_the_day_may_go_over():
    food = with_nutrient("calories", {"lo": 200, "hi": 300}, "meal")
    calories = rule(evaluate(food, 1, Profile(), consumed={"calories": 1750}), "calories")
    assert calories["status"] == "warn"
    assert "may go over today's goal" in calories["detail"]


def test_calories_daily_warning_does_not_downgrade_a_per_meal_failure():
    food = with_nutrient("calories", {"lo": 700, "hi": 900}, "meal")
    calories = rule(evaluate(food, 1, Profile(), consumed={"calories": 1200}), "calories")
    assert calories["status"] == "fail"


# ------------------------------------------------------------------ protein


def test_protein_meeting_the_target_passes():
    protein = rule(evaluate(item(), 1, Profile()), "protein")
    assert protein["status"] == "pass" and "meets" in protein["detail"]


def test_protein_short_of_target_warns_with_percentage():
    protein = rule(evaluate(with_nutrient("protein_g", exact(10)), 1, Profile()), "protein")
    assert protein["status"] == "warn"
    assert "40%" in protein["detail"]


def test_protein_never_fails():
    protein = rule(evaluate(with_nutrient("protein_g", exact(0)), 1, Profile()), "protein")
    assert protein["status"] == "warn"


def test_protein_range_uses_its_low_end():
    food = with_nutrient("protein_g", {"lo": 20, "hi": 30}, "meal")
    assert rule(evaluate(food, 1, Profile()), "protein")["status"] == "warn"


# ---------------------------------------------------------------- allergens


def allergen_rule(typed, source="label", **fields):
    food = item(source, **fields)
    result = evaluate(food, 1, Profile(allergens=[typed]))
    return rule(result, f"allergen:{typed.lower()}"), result


@pytest.mark.parametrize("typed, ingredient", [
    ("peanut", "groundnut oil"),
    ("peanuts", "roasted peanuts"),
    ("dairy", "ghee"),
    ("milk", "paneer"),
    ("milk", "dahi"),
    ("milk", "khoa"),
    ("lactose", "whey powder"),
    ("gluten", "maida"),
    ("wheat", "atta"),
    ("wheat", "rava"),
    ("gluten", "suji"),
    ("nuts", "cashew"),
    ("nuts", "groundnut"),
    ("tree nuts", "almonds"),
    ("eggs", "egg white powder"),
    ("soya", "soy lecithin"),
    ("fish", "anchovies"),
    ("shellfish", "prawn powder"),
    ("seafood", "crab extract"),
    ("sesame", "til"),
    ("mustard", "sarson oil"),
    ("sulphites", "preservative (E223)"),
])
def test_allergen_aliases_and_indian_terms_fail(typed, ingredient):
    found, result = allergen_rule(typed, ingredients=["sugar", ingredient])
    assert found["status"] == "fail", found
    assert result["overall"] == "red"


@pytest.mark.parametrize("typed, ingredient", [
    ("peanut", "मूंगफली"),
    ("peanut", "મગફળી તેલ"),
    ("milk", "दूध पाउडर"),
    ("milk", "દૂધ"),
    ("wheat", "गेहूं का आटा"),
    ("wheat", "ઘઉંનો લોટ"),
])
def test_allergen_hindi_and_gujarati_terms_fail(typed, ingredient):
    found, _ = allergen_rule(typed, ingredients=[ingredient])
    assert found["status"] == "fail", found


def test_allergen_failure_names_the_matched_term():
    found, _ = allergen_rule("dairy", ingredients=["sugar", "Milk Solids"])
    assert '"milk"' in found["detail"] and "Milk Solids" in found["detail"]


@pytest.mark.parametrize("typed, ingredients", [
    ("milk", ["cocoa butter", "shea butter", "peanut butter"]),
    ("milk", ["coconut milk", "almond milk"]),
    ("tree nut", ["coconut", "nutmeg", "desiccated coconut"]),
    ("tree nut", ["groundnut oil"]),
    ("egg", ["eggplant"]),
    ("fish", ["shellfish extract"]),
    ("wheat", ["buckwheat", "gluten-free oats"]),
])
def test_allergen_exclusion_phrases_do_not_raise_false_alarms(typed, ingredients):
    found, _ = allergen_rule(typed, ingredients=ingredients)
    assert found["status"] == "pass", found


def test_allergen_in_contains_statement_fails():
    found, _ = allergen_rule("milk", ingredients=["sugar"], contains=["Milk", "Soy"])
    assert found["status"] == "fail"


def test_allergen_only_in_may_contain_warns():
    found, _ = allergen_rule("peanut", ingredients=["sugar"], may_contain=["peanuts"])
    assert found["status"] == "warn"
    assert "May contain peanut" in found["detail"]


def test_allergen_ingredients_not_read_warns():
    found, result = allergen_rule("peanut", ingredients=[])
    assert found["status"] == "warn"
    assert found["detail"] == INGREDIENTS_NOT_READ
    assert result["overall"] == "amber"


def test_allergen_absent_from_ingredients_passes():
    found, _ = allergen_rule("peanut", ingredients=["rice", "salt"])
    assert found["status"] == "pass"


def test_unknown_allergen_is_matched_literally():
    assert allergen_rule("kiwi", ingredients=["kiwis", "apple"])[0]["status"] == "fail"
    assert allergen_rule("kiwi", ingredients=["apple"])[0]["status"] == "pass"


def test_meal_allergen_match_fails():
    found, _ = allergen_rule("milk", "meal", ingredients=["paneer", "tomato"])
    assert found["status"] == "fail"


def test_meal_allergen_match_in_dish_name_fails():
    found, _ = allergen_rule("milk", "meal", name="Paneer tikka", ingredients=["spices"])
    assert found["status"] == "fail"


def test_meal_without_a_match_still_warns():
    found, result = allergen_rule("peanut", "meal", ingredients=["rice", "dal"])
    assert found["status"] == "warn"
    assert found["detail"] == MEAL_ALLERGEN_WARNING
    assert result["overall"] == "amber"


def test_disclaimer_appears_only_when_the_profile_has_allergens():
    assert evaluate(item(), 1, Profile(allergens=["peanut"]))["disclaimer"] == ALLERGEN_DISCLAIMER
    assert evaluate(item(), 1, Profile())["disclaimer"] is None


def test_each_profile_allergen_gets_its_own_rule():
    result = evaluate(item(ingredients=["ghee", "rice"]), 1, Profile(allergens=["peanut", "dairy"]))
    assert rule(result, "allergen:peanut")["status"] == "pass"
    assert rule(result, "allergen:dairy")["status"] == "fail"


# --------------------------------------------------------------------- diet


def diet_rule(diet, source="label", **fields):
    result = evaluate(item(source, **fields), 1, Profile(diet=diet))
    return rule(result, "diet"), result


def test_no_diet_adds_no_rule():
    assert "diet" not in rule_ids(evaluate(item(ingredients=["pork"]), 1, Profile(diet="none")))


@pytest.mark.parametrize("diet, ingredient", [
    ("vegetarian", "chicken"),
    ("vegetarian", "fish sauce"),
    ("vegetarian", "gelatine"),
    ("vegetarian", "lard"),
    ("vegetarian", "rennet"),
    ("vegetarian", "colour (E120)"),
    ("eggetarian", "carmine"),
    ("eggetarian", "prawns"),
    ("vegan", "milk solids"),
    ("vegan", "egg"),
    ("vegan", "honey"),
    ("vegan", "gelatin"),
    ("jain", "onion powder"),
    ("jain", "garlic"),
    ("jain", "potatoes"),
    ("jain", "carrot"),
    ("jain", "radish"),
    ("jain", "beetroot"),
    ("jain", "ginger"),
    ("jain", "mushroom"),
    ("jain", "yeast extract"),
    ("jain", "egg"),
    ("jain", "honey"),
    ("jain", "mutton"),
    ("halal", "pork fat"),
    ("halal", "lard"),
    ("halal", "gelatin"),
    ("halal", "alcohol"),
    ("halal", "red wine"),
    ("halal", "beer"),
    ("halal", "rum"),
    ("halal", "carmine"),
])
def test_diet_conflict_fails(diet, ingredient):
    found, result = diet_rule(diet, ingredients=["sugar", ingredient])
    assert found["status"] == "fail", found
    assert result["overall"] == "red"


@pytest.mark.parametrize("diet, ingredients", [
    ("vegetarian", ["milk", "egg", "microbial rennet", "honey"]),
    ("eggetarian", ["egg", "milk"]),
    ("vegan", ["cocoa butter", "coconut milk", "sugar"]),
    ("jain", ["rice", "ghee", "tomato"]),
    ("halal", ["chicken", "sugar alcohol", "ginger beer"]),
])
def test_diet_without_conflict_passes(diet, ingredients):
    found, _ = diet_rule(diet, ingredients=ingredients)
    assert found["status"] == "pass", found


def test_diet_with_unread_ingredients_warns():
    found, _ = diet_rule("vegan", ingredients=[])
    assert found["status"] == "warn"


def test_diet_check_reads_meal_item_names():
    found, _ = diet_rule("vegetarian", "meal", ingredients=["rice", "spices"],
                         items=[{"name": "chicken biryani", "portion": "1 plate"}])
    assert found["status"] == "fail"


@pytest.mark.parametrize("diet", ["jain", "halal"])
def test_jain_and_halal_add_a_certification_note(diet):
    _, result = diet_rule(diet)
    assert len(result["notes"]) == 1
    assert "certification" in result["notes"][0]


def test_other_diets_add_no_note():
    assert diet_rule("vegan")[1]["notes"] == []
