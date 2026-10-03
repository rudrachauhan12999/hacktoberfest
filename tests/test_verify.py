"""The verifiers: one test per error type, plus the answers that must pass."""

from app.verify import verify_label, verify_meal

from .conftest import label_reading, meal_reading


def only_error(errors: list[str]) -> str:
    assert len(errors) == 1, errors
    return errors[0]


# ------------------------------------------------------------------ labels


def test_label_plausible_reading_passes():
    assert verify_label(label_reading()) == []


def test_label_kj_and_salt_only_passes():
    reading = label_reading(calories=None, energy_kj=669, sodium_mg=None, salt_g=0.4)
    assert verify_label(reading) == []


def test_label_nothing_read():
    empty = {key: None for key in label_reading()} | {"basis": "per_serving", "ingredients": []}
    assert "No nutrition values were read" in only_error(verify_label(empty))


def test_label_negative_value():
    assert "fiber is -1" in only_error(verify_label(label_reading(fiber_g=-1)))


def test_label_per_100g_macros_over_100():
    reading = label_reading(basis="per_100g", serving_size_g=None, calories=560,
                            protein_g=40, carbs_g=50, sugar_g=5, fat_g=20)
    error = only_error(verify_label(reading))
    assert "110 g" in error and "100 g" in error


def test_label_per_100g_macros_at_limit_pass():
    reading = label_reading(basis="per_100g", serving_size_g=None, calories=400,
                            protein_g=0, carbs_g=100.4, sugar_g=99, fat_g=0)
    assert verify_label(reading) == []


def test_label_per_serving_macros_exceed_serving_size():
    error = only_error(verify_label(label_reading(serving_size_g=20)))
    assert "27 g" in error and "serving size of 20 g" in error


def test_label_per_serving_macros_within_five_percent_pass():
    # 27 g of macros in a 26 g serving is inside the 5% tolerance.
    assert verify_label(label_reading(serving_size_g=26)) == []


def test_label_sugar_above_carbs():
    error = only_error(verify_label(label_reading(sugar_g=16)))
    assert "sugar is 16 g" in error and "15 g" in error


def test_label_sugar_within_half_gram_of_carbs_passes():
    assert verify_label(label_reading(sugar_g=15.4)) == []


def test_label_per_100g_calories_above_905():
    reading = label_reading(basis="per_100g", serving_size_g=None, calories=950,
                            protein_g=None, carbs_g=None, sugar_g=None, fat_g=100)
    assert "950 kcal per 100 g" in only_error(verify_label(reading))


def test_label_calories_above_3000():
    reading = label_reading(calories=3200, protein_g=None, carbs_g=None, sugar_g=None, fat_g=None)
    assert "3000 kcal" in only_error(verify_label(reading))


def test_label_sodium_above_10000_mg():
    assert "10000 mg" in only_error(verify_label(label_reading(sodium_mg=12000)))


def test_label_sodium_from_salt_above_10000_mg():
    error = only_error(verify_label(label_reading(sodium_mg=None, salt_g=30)))
    assert "sodium is 12000 mg" in error


def test_label_calories_disagree_with_macros():
    error = only_error(verify_label(label_reading(calories=60)))
    assert "60 kcal" in error and "158 kcal" in error


def test_label_calorie_check_uses_larger_of_25_kcal_and_20_percent():
    # Macros give 158 kcal. 25 kcal applies below 125 kcal, 20% above it.
    assert verify_label(label_reading(calories=135)) == []       # 23 off, 20% is 27
    assert verify_label(label_reading(calories=195)) == []       # 37 off, 20% is 39
    assert verify_label(label_reading(calories=200)) != []       # 42 off, 20% is 40


def test_label_calorie_check_skipped_when_a_macro_is_missing():
    assert verify_label(label_reading(calories=60, fat_g=None)) == []


# ------------------------------------------------------------------- meals


def test_meal_plausible_estimate_passes():
    assert verify_meal(meal_reading()) == []


def test_meal_empty_items():
    assert "items list is empty" in only_error(verify_meal(meal_reading(items=[])))


def test_meal_min_above_max():
    error = only_error(verify_meal(meal_reading(protein_g_min=25)))
    assert "protein minimum 25" in error and "maximum 20" in error


def test_meal_negative_value():
    errors = verify_meal(meal_reading(fat_g_min=-2))
    assert any("cannot be negative" in error for error in errors)


def test_meal_calorie_midpoint_above_3500():
    reading = meal_reading(calories_min=3600, calories_max=4000, protein_g_min=100,
                           protein_g_max=120, carbs_g_min=400, carbs_g_max=460,
                           fat_g_min=170, fat_g_max=190)
    assert "3500 kcal" in only_error(verify_meal(reading))


def test_meal_calories_disagree_with_macros():
    error = only_error(verify_meal(meal_reading(calories_min=900, calories_max=1000)))
    assert "950 kcal" in error and "434 kcal" in error


def test_meal_calorie_check_uses_larger_of_60_kcal_and_25_percent():
    # Macro midpoints give 434 kcal.
    assert verify_meal(meal_reading(calories_min=370, calories_max=390)) == []   # 54 off
    assert verify_meal(meal_reading(calories_min=540, calories_max=600)) == []   # 136 off, 25% is 142
    assert verify_meal(meal_reading(calories_min=580, calories_max=620)) != []   # 166 off, 25% is 150


def test_meal_missing_bound():
    assert "fat needs both" in only_error(verify_meal(meal_reading(fat_g_max=None)))
